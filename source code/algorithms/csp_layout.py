import random
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from city.constants import LocationType
from city.graph import CityGraph
import config

Assignment = Dict[str, int]


@dataclass
class CSPResult:
    success: bool
    assignment: Assignment = field(default_factory=dict)
    conflicts: List[str] = field(default_factory=list)
    message: str = ""


def debugPrintAssignment(assignment, solver):
    print(f"\n{'='*55}")
    print(f"{'VAR':<6} {'TYPE':<20} {'ROW':<5} {'COL':<5}")
    print(f"{'='*55}")
    for var in sorted(assignment.keys()):
        nodeId = assignment[var]
        row, col = solver.rowColCache[nodeId]
        typeName = solver.variableType[var].name
        print(f"{var:<6} {typeName:<20} {row:<5} {col:<5}")
    print(f"{'='*55}")

    typeCounts = Counter(solver.variableType[v].name for v in assignment)
    print("\nCOUNT SUMMARY:")
    for t, count in sorted(typeCounts.items()):
        print(f"  {t:<22} {count}")
    print(f"{'='*55}")

    ok = solver.checkAllConstraints(assignment)
    if ok:
        print("CONSTRAINT CHECK: ALL PASSED OK")
    else:
        print("CONSTRAINT CHECK: VIOLATIONS FOUND FAIL")
        for c in solver.lastConflicts:
            print(f"  - {c}")
    print(f"{'='*55}\n")


class CityLayoutCSP:

    powerMaxHops = 2
    residentMaxHops = 3
    industrialBufferMinDist = 3
    depotMaxHops = 8

    tierOrder = ["H", "I", "P", "S", "D", "R"]

    def __init__(self, city: CityGraph, seed: Optional[int] = None):
        self.city = city
        self.random = random.Random(seed)

        self.hospitalSpread = 6
        self.depotMaxHops = max(4, min(8, int(min(city.rows, city.cols) * 0.4)))

        self.variables: List[str] = self.buildVariableList()
        self.variableType: Dict[str, LocationType] = self.buildVariableTypes()

        self.rowColCache: Dict[int, Tuple[int, int]] = {
            nid: city.rowCol(nid) for nid in city.allNodeIds()
        }

        self.domains: Dict[str, List[int]] = self.buildStratifiedDomains()

        self.constraintNeighbors: Dict[str, List[str]] = self.buildConstraintNeighborMap()

        self.tieredVars: List[List[str]] = self.buildTieredVarGroups()

        self.lastConflicts: List[str] = []
        self.searchDeadline: float = 0.0

    def buildVariableList(self):
        variables: List[str] = []
        for i in range(config.numHospitals):
            variables.append(f"H{i+1}")
        for i in range(config.numIndustrial):
            variables.append(f"I{i+1}")
        for i in range(config.numPowerPlants):
            variables.append(f"P{i+1}")
        for i in range(config.numSchools):
            variables.append(f"S{i+1}")
        for i in range(config.numDepots):
            variables.append(f"D{i+1}")
        for i in range(config.numResidential):
            variables.append(f"R{i+1}")
        return variables

    def buildVariableTypes(self):
        prefixMap = {
            "H": LocationType.HOSPITAL,
            "I": LocationType.INDUSTRIAL,
            "S": LocationType.SCHOOL,
            "P": LocationType.POWER_PLANT,
            "D": LocationType.AMBULANCE_DEPOT,
            "R": LocationType.RESIDENTIAL,
        }
        result = {var: prefixMap[var[0]] for var in self.variables}
        return result

    def buildStratifiedDomains(self):
        allCells = list(self.city.allNodeIds())
        rows, cols = self.city.rows, self.city.cols

        marginRow = max(1, int(rows * 0.35))
        marginCol = max(1, int(cols * 0.35))
        outerCells = []
        for nid in allCells:
            r, c = self.rowColCache[nid]
            if r < marginRow or r >= rows - marginRow or c < marginCol or c >= cols - marginCol:
                outerCells.append(nid)
        if len(outerCells) < config.numIndustrial * 4:
            outerCells = list(allCells)

        interiorRowLow = marginRow
        interiorRowHigh = rows - marginRow - 1
        interiorColLow = marginCol
        interiorColHigh = cols - marginCol - 1

        def isNearSensitiveZone(nid: int):
            r, c = self.rowColCache[nid]
            dr = max(0, interiorRowLow - r, r - interiorRowHigh)
            dc = max(0, interiorColLow - c, c - interiorColHigh)
            return (dr + dc) < self.industrialBufferMinDist

        outerBuffered = [nid for nid in outerCells if not isNearSensitiveZone(nid)]
        if len(outerBuffered) < config.numIndustrial * 4:
            outerBuffered = outerCells

        outerBufferedSet: Set[int] = set(outerBuffered)
        powerCandidates = []
        for nid in allCells:
            nr, nc = self.rowColCache[nid]
            for o in outerBufferedSet:
                or_, oc = self.rowColCache[o]
                if abs(nr - or_) + abs(nc - oc) <= self.powerMaxHops:
                    powerCandidates.append(nid)
                    break

        powerBuffered = [nid for nid in powerCandidates if not isNearSensitiveZone(nid)]
        if len(powerBuffered) < config.numPowerPlants * 4:
            powerBuffered = powerCandidates
        if len(powerBuffered) < config.numPowerPlants * 4:
            powerBuffered = list(allCells)

        interiorCells = []
        for nid in allCells:
            r, c = self.rowColCache[nid]
            if 2 <= r <= rows - 3 and 2 <= c <= cols - 3:
                interiorCells.append(nid)
        self.gridMidRow = rows // 2
        self.gridMidCol = cols // 2

        domains: Dict[str, List[int]] = {}
        for var in self.variables:
            prefix = var[0]
            if prefix == "H":
                base = interiorCells[:]
            elif prefix == "I":
                base = outerBuffered[:]
            elif prefix == "P":
                base = powerBuffered[:]
            else:
                base = allCells[:]
            self.random.shuffle(base)
            domains[var] = base
        return domains

    def buildConstraintNeighborMap(self):
        sensitivePrefixes = {"S", "H"}
        neighbors: Dict[str, List[str]] = {v: [] for v in self.variables}

        for var1 in self.variables:
            type1 = var1[0]
            for var2 in self.variables:
                if var1 == var2:
                    continue
                type2 = var2[0]
                linked = (
                    (type1 == "I" and type2 in sensitivePrefixes) or
                    (type1 in sensitivePrefixes and type2 == "I") or
                    (type1 == "H" and type2 == "H") or
                    (type1 == "P" and type2 == "I") or
                    (type1 == "I" and type2 == "P") or
                    (type1 == "R" and type2 == "H") or
                    (type1 == "H" and type2 == "R")
                )
                if linked:
                    neighbors[var1].append(var2)
        return neighbors

    def buildTieredVarGroups(self):
        tierMap: Dict[str, List[str]] = {p: [] for p in self.tierOrder}
        for var in self.variables:
            tierMap[var[0]].append(var)
        result = [tierMap[p] for p in self.tierOrder]
        return result

    def manhattanDistance(self, a: int, b: int):
        ar, ac = self.rowColCache[a]
        br, bc = self.rowColCache[b]
        result = abs(ar - br) + abs(ac - bc)
        return result

    def areAdjacent(self, a: int, b: int):
        ar, ac = self.rowColCache[a]
        br, bc = self.rowColCache[b]
        result = abs(ar - br) + abs(ac - bc) == 1
        return result

    def buildArcList(self):
        arcs: List[Tuple[str, str]] = []
        seen: Set[Tuple[str, str]] = set()
        for var1, neighbors in self.constraintNeighbors.items():
            for var2 in neighbors:
                for pair in [(var1, var2), (var2, var1)]:
                    if pair not in seen:
                        arcs.append(pair)
                        seen.add(pair)
        return arcs

    def reviseArc(self, xi: str, xj: str):
        typeXi = self.variableType[xi]
        typeXj = self.variableType[xj]
        sensitiveTypes = frozenset([LocationType.SCHOOL, LocationType.HOSPITAL])
        newDomain: List[int] = []
        revised = False

        for valueXi in self.domains[xi]:
            hasSupport = False
            for valueXj in self.domains[xj]:
                if valueXi == valueXj:
                    continue
                valid = True

                if (typeXi == LocationType.INDUSTRIAL and typeXj in sensitiveTypes) or \
                   (typeXj == LocationType.INDUSTRIAL and typeXi in sensitiveTypes):
                    if self.areAdjacent(valueXi, valueXj):
                        valid = False

                if valid and typeXi == LocationType.HOSPITAL and typeXj == LocationType.HOSPITAL:
                    if self.manhattanDistance(valueXi, valueXj) < self.hospitalSpread:
                        valid = False

                if valid and typeXi == LocationType.POWER_PLANT and typeXj == LocationType.INDUSTRIAL:
                    if self.manhattanDistance(valueXi, valueXj) > self.powerMaxHops:
                        valid = False

                if valid and typeXi == LocationType.RESIDENTIAL and typeXj == LocationType.HOSPITAL:
                    if self.manhattanDistance(valueXi, valueXj) > self.residentMaxHops:
                        valid = False

                if valid:
                    hasSupport = True
                    break

            if hasSupport:
                newDomain.append(valueXi)
            else:
                revised = True

        self.domains[xi] = newDomain
        return revised

    def runAC3(self):
        queue: deque = deque(self.buildArcList())
        neighborSets: Dict[str, Set[str]] = {
            v: set(ns) for v, ns in self.constraintNeighbors.items()
        }

        while queue:
            xi, xj = queue.popleft()
            if self.reviseArc(xi, xj):
                if not self.domains[xi]:
                    self.lastConflicts.append(
                        f"AC-3: domain of {xi} became empty -- constraint unsatisfiable"
                    )
                    return False
                for xk in neighborSets.get(xi, set()):
                    if xk != xj:
                        queue.append((xk, xi))
        return True

    def isValueConsistentWithAssignment(self, var: str, value: int, assignment: Assignment):
        varType = self.variableType[var]
        sensitiveTypes = frozenset([LocationType.SCHOOL, LocationType.HOSPITAL])
        self.lastConflicts = []

        for other, otherValue in assignment.items():
            otherType = self.variableType[other]

            if otherValue == value:
                self.lastConflicts.append("AllDiff: cell already occupied")
                return False

            if (varType == LocationType.INDUSTRIAL and otherType in sensitiveTypes) or \
               (otherType == LocationType.INDUSTRIAL and varType in sensitiveTypes):
                if self.areAdjacent(value, otherValue):
                    self.lastConflicts.append(
                        "AdjProhibition: Industrial adjacent to School/Hospital"
                    )
                    return False

            if varType == LocationType.HOSPITAL and otherType == LocationType.HOSPITAL:
                if self.manhattanDistance(value, otherValue) < self.hospitalSpread:
                    self.lastConflicts.append(
                        f"HospitalSpread: distance {self.manhattanDistance(value, otherValue)} "
                        f"< {self.hospitalSpread}"
                    )
                    return False

        if varType == LocationType.POWER_PLANT:
            placedIndustrials = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.INDUSTRIAL:
                    placedIndustrials.append(v)
            if placedIndustrials:
                if min(self.manhattanDistance(value, i) for i in placedIndustrials) > self.powerMaxHops:
                    self.lastConflicts.append(
                        "PowerProximity: Power Plant not within 2 hops of any Industrial"
                    )
                    return False

        if varType == LocationType.RESIDENTIAL:
            placedHospitals = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.HOSPITAL:
                    placedHospitals.append(v)
            if placedHospitals:
                if min(self.manhattanDistance(value, h) for h in placedHospitals) > self.residentMaxHops:
                    self.lastConflicts.append(
                        "ResidentCoverage: Residential not within 3 hops of Hospital"
                    )
                    return False

        if varType == LocationType.AMBULANCE_DEPOT:
            placedHospitals = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.HOSPITAL:
                    placedHospitals.append(v)
            if placedHospitals:
                if min(self.manhattanDistance(value, h) for h in placedHospitals) > self.depotMaxHops:
                    self.lastConflicts.append(
                        f"DepotProximity: Depot not within {self.depotMaxHops} hops of any Hospital"
                    )
                    return False

        return True

    def checkAllConstraints(self, assignment: Assignment):
        placedHospitals = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.HOSPITAL:
                placedHospitals.append(v)
        placedIndustrials = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.INDUSTRIAL:
                placedIndustrials.append(v)
        placedSchools = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.SCHOOL:
                placedSchools.append(v)
        placedPowerPlants = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.POWER_PLANT:
                placedPowerPlants.append(v)
        placedResidentials = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.RESIDENTIAL:
                placedResidentials.append(v)
        conflicts: List[str] = []

        if len(set(assignment.values())) != len(assignment):
            conflicts.append("AllDiff: two locations share a cell")

        for industrial in placedIndustrials:
            for sensitive in placedSchools + placedHospitals:
                if self.areAdjacent(industrial, sensitive):
                    conflicts.append("AdjProhibition: Industrial adjacent to School/Hospital")
                    break

        for idx, hospital1 in enumerate(placedHospitals):
            for hospital2 in placedHospitals[idx + 1:]:
                if self.manhattanDistance(hospital1, hospital2) < self.hospitalSpread:
                    conflicts.append(
                        f"HospitalSpread: hospitals {self.manhattanDistance(hospital1, hospital2)} apart "
                        f"(need >= {self.hospitalSpread})"
                    )

        for powerPlant in placedPowerPlants:
            if not placedIndustrials or \
               min(self.manhattanDistance(powerPlant, i) for i in placedIndustrials) > self.powerMaxHops:
                conflicts.append("PowerProximity: Power Plant not within 2 hops of Industrial")

        for residential in placedResidentials:
            if not placedHospitals or \
               min(self.manhattanDistance(residential, h) for h in placedHospitals) > self.residentMaxHops:
                conflicts.append("ResidentCoverage: Residential not within 3 hops of Hospital")

        placedDepots = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.AMBULANCE_DEPOT:
                placedDepots.append(v)
        for depot in placedDepots:
            if not placedHospitals or \
               min(self.manhattanDistance(depot, h) for h in placedHospitals) > self.depotMaxHops:
                conflicts.append(f"DepotProximity: Depot not within {self.depotMaxHops} hops of any Hospital")

        self.lastConflicts = sorted(set(conflicts))
        result = len(self.lastConflicts) == 0
        return result

    def getLegalValues(self, var: str, assignment: Assignment):
        result = [v for v in self.domains[var] if self.isValueConsistentWithAssignment(var, v, assignment)]
        return result

    def selectMRVVariable(self, unassignedTier: List[str], assignment: Assignment):
        bestVar: Optional[str] = None
        bestCount = float("inf")

        for var in unassignedTier:
            count = 0
            for v in self.domains[var]:
                if self.isValueConsistentWithAssignment(var, v, assignment):
                    count += 1
            if count == 0:
                return var
            if count < bestCount:
                bestCount = count
                bestVar = var

        return bestVar

    def getLCVOrderedValues(self, var: str, assignment: Assignment):
        legalValues = self.getLegalValues(var, assignment)
        usedCells = set(assignment.values())

        if var[0] == "H":
            placedHospitals = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.HOSPITAL:
                    placedHospitals.append(v)
            if placedHospitals:
                def hospitalScore(value: int, placed=placedHospitals):
                    vr, vc = self.rowColCache[value]
                    minDist = min(self.manhattanDistance(value, h) for h in placed)
                    sameQuadrant = sum(
                        1 for h in placed
                        if (self.rowColCache[h][0] >= self.gridMidRow) == (vr >= self.gridMidRow)
                        and (self.rowColCache[h][1] >= self.gridMidCol) == (vc >= self.gridMidCol)
                    )
                    return (sameQuadrant * 100) - minDist
                result = sorted(legalValues, key=hospitalScore)
                return result
            return legalValues

        if var[0] in ("I", "P"):
            placedIndustrials = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.INDUSTRIAL:
                    placedIndustrials.append(v)
            placedIndustrialAndPower = []
            for k, v in assignment.items():
                if self.variableType[k] in (LocationType.INDUSTRIAL, LocationType.POWER_PLANT):
                    placedIndustrialAndPower.append(v)

            if var[0] == "P" and placedIndustrials:
                def powerPlantScore(value: int):
                    distToNearest = min(self.manhattanDistance(value, i) for i in placedIndustrials)
                    industrialProximityScore = 100 - min(distToNearest, 100)
                    clusterProximityScore = 0
                    if placedIndustrialAndPower:
                        distToCluster = min(self.manhattanDistance(value, ip) for ip in placedIndustrialAndPower)
                        clusterProximityScore = 100 - min(distToCluster, 100)
                    return (industrialProximityScore, clusterProximityScore)
                result = sorted(legalValues, key=powerPlantScore, reverse=True)
                return result

            def industrialScore(value: int):
                r, c = self.rowColCache[value]
                clusterSize = 0
                for nr in range(r - 2, r + 3):
                    for nc in range(c - 2, c + 3):
                        if nr == r and nc == c:
                            continue
                        if self.city.inBounds(nr, nc):
                            nid = self.city.nodeId(nr, nc)
                            if nid not in usedCells and nid in self.domains[var]:
                                clusterSize += 1
                clusterProximityBonus = 0
                if placedIndustrialAndPower:
                    distToCluster = min(self.manhattanDistance(value, ip) for ip in placedIndustrialAndPower)
                    clusterProximityBonus = 100 - min(distToCluster, 100)
                return (clusterSize, clusterProximityBonus)
            result = sorted(legalValues, key=industrialScore, reverse=True)
            return result

        if var[0] == "R":
            placedHospitals = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.HOSPITAL:
                    placedHospitals.append(v)
            if not placedHospitals:
                return legalValues

            def residentialScore(value: int):
                ar, ac = self.rowColCache[value]
                result = min(abs(ar - self.rowColCache[h][0]) + abs(ac - self.rowColCache[h][1])
                           for h in placedHospitals)
                return result
            result = sorted(legalValues, key=residentialScore)
            return result

        if var[0] == "S":
            placedHospitals = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.HOSPITAL:
                    placedHospitals.append(v)
            if placedHospitals:
                def schoolScore(value: int):
                    ar, ac = self.rowColCache[value]
                    result = min(abs(ar - self.rowColCache[h][0]) + abs(ac - self.rowColCache[h][1])
                               for h in placedHospitals)
                    return result
                result = sorted(legalValues, key=schoolScore)
                return result
            return legalValues

        if len(legalValues) > 20:
            return legalValues

        unconstrainedNeighbors = [
            nb for nb in self.constraintNeighbors.get(var, [])
            if nb not in assignment
        ]
        if not unconstrainedNeighbors:
            return legalValues

        def standardLCVScore(value: int):
            tempAssignment = {**assignment, var: value}
            score = sum(
                sum(1 for v in self.domains[nb] if self.isValueConsistentWithAssignment(nb, v, tempAssignment))
                for nb in unconstrainedNeighbors
            )
            return score
        result = sorted(legalValues, key=standardLCVScore, reverse=True)
        return result

    def forwardCheck(self, var: str, value: int, assignment: Assignment):
        tempAssignment = {**assignment, var: value}
        for neighbor in self.constraintNeighbors.get(var, []):
            if neighbor in assignment:
                continue
            hasLegal = False
            for v in self.domains[neighbor]:
                if self.isValueConsistentWithAssignment(neighbor, v, tempAssignment):
                    hasLegal = True
                    break
            if not hasLegal:
                return False
        return True

    def narrowResidentialDomains(self, assignment: Assignment):
        placedHospitals = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.HOSPITAL:
                placedHospitals.append(v)
        if len(placedHospitals) < config.numHospitals:
            return

        usedCells = set(assignment.values())
        allNodes = list(self.city.allNodeIds())

        residentialVars = sorted(
            [v for v in self.variables if v[0] == "R" and v not in assignment],
            key=lambda v: int(v[1:])
        )
        if not residentialVars:
            return

        reachableFromAnyHospital = []
        for nid in allNodes:
            if nid not in usedCells and any(self.manhattanDistance(nid, h) <= self.residentMaxHops for h in placedHospitals):
                reachableFromAnyHospital.append(nid)
        if len(reachableFromAnyHospital) < len(residentialVars):
            return

        reachableSet = set(reachableFromAnyHospital)

        perHospitalReachable = []
        for h in placedHospitals:
            reachableForH = set()
            for nid in allNodes:
                if nid not in usedCells and self.manhattanDistance(nid, h) <= self.residentMaxHops:
                    reachableForH.add(nid)
            perHospitalReachable.append(reachableForH)

        buckets = {i: [] for i in range(len(placedHospitals))}
        for idx, var in enumerate(residentialVars):
            buckets[idx % len(placedHospitals)].append(var)

        for hospitalIdx, bucketVars in buckets.items():
            hospitalReachable = perHospitalReachable[hospitalIdx]
            if len(hospitalReachable) < len(bucketVars):
                hospitalReachable = reachableSet
            for var in bucketVars:
                narrowed = [v for v in self.domains[var] if v in hospitalReachable]
                if narrowed:
                    self.domains[var] = narrowed

    def backtrack(
        self,
        assignment: Assignment,
        tierIndex: int,
        remainingInTier: List[str],
        stepLimit: List[int],
        residentialNarrowed: List[bool],
    ):
        if time.time() > self.searchDeadline or stepLimit[0] <= 0:
            return None

        while tierIndex < len(self.tieredVars) and not remainingInTier:
            tierIndex += 1
            if tierIndex < len(self.tieredVars):
                tierPrefix = self.tierOrder[tierIndex] if tierIndex < len(self.tierOrder) else ""
                if tierPrefix == "R" and not residentialNarrowed[0]:
                    residentialNarrowed[0] = True
                    self.narrowResidentialDomains(assignment)
                remainingInTier = [
                    v for v in self.tieredVars[tierIndex] if v not in assignment
                ]

        if tierIndex >= len(self.tieredVars):
            if self.checkAllConstraints(assignment):
                return dict(assignment)
            return None

        stepLimit[0] -= 1

        var = self.selectMRVVariable(remainingInTier, assignment)
        if var is None:
            return None

        nextRemaining = [v for v in remainingInTier if v != var]

        if var[0] == "R":
            usedCells = set(assignment.values())
            for value in self.domains[var]:
                if value in usedCells:
                    continue
                if self.isValueConsistentWithAssignment(var, value, assignment):
                    assignment[var] = value
                    result = self.backtrack(assignment, tierIndex, nextRemaining, stepLimit, residentialNarrowed)
                    if result is not None:
                        return result
                    del assignment[var]
            return None

        for value in self.getLCVOrderedValues(var, assignment):
            assignment[var] = value
            if self.forwardCheck(var, value, assignment):
                if var[0] == "H":
                    self.narrowResidentialDomains(assignment)
                result = self.backtrack(assignment, tierIndex, nextRemaining, stepLimit, residentialNarrowed)
                if result is not None:
                    return result
            del assignment[var]

        return None

    def findMinimumViolationSolution(self, numRestarts: int = 30):
        allNodes = list(self.city.allNodeIds())

        def makeRandomAssignment():
            result: Assignment = {}
            usedCells: Set[int] = set()
            for var in self.variables:
                pool = [n for n in self.domains[var] if n not in usedCells] or allNodes
                chosen = self.random.choice(pool)
                result[var] = chosen
                usedCells.add(chosen)
            return result

        def countViolations(assignment: Assignment):
            placedHospitals = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.HOSPITAL:
                    placedHospitals.append(v)
            placedIndustrials = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.INDUSTRIAL:
                    placedIndustrials.append(v)
            placedSchools = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.SCHOOL:
                    placedSchools.append(v)
            placedPowerPlants = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.POWER_PLANT:
                    placedPowerPlants.append(v)
            placedResidentials = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.RESIDENTIAL:
                    placedResidentials.append(v)
            count = 0

            if len(set(assignment.values())) != len(assignment):
                count += len(assignment) - len(set(assignment.values()))

            for industrial in placedIndustrials:
                for sensitive in placedSchools + placedHospitals:
                    if self.areAdjacent(industrial, sensitive):
                        count += 1

            for powerPlant in placedPowerPlants:
                if placedIndustrials and \
                   min(self.manhattanDistance(powerPlant, i) for i in placedIndustrials) > self.powerMaxHops:
                    count += 1

            for residential in placedResidentials:
                if placedHospitals and \
                   min(self.manhattanDistance(residential, h) for h in placedHospitals) > self.residentMaxHops:
                    count += 1

            placedDepots = []
            for k, v in assignment.items():
                if self.variableType[k] == LocationType.AMBULANCE_DEPOT:
                    placedDepots.append(v)
            for depot in placedDepots:
                if placedHospitals and \
                   min(self.manhattanDistance(depot, h) for h in placedHospitals) > self.depotMaxHops:
                    count += 1

            return count

        bestAssignment = makeRandomAssignment()
        bestViolationCount = countViolations(bestAssignment)

        for _ in range(numRestarts - 1):
            if bestViolationCount == 0:
                break
            candidate = makeRandomAssignment()
            violations = countViolations(candidate)
            if violations < bestViolationCount:
                bestViolationCount = violations
                bestAssignment = candidate

        self.diagnoseFinalViolations(bestAssignment, bestViolationCount)
        return bestAssignment, bestViolationCount

    def diagnoseFinalViolations(self, assignment: Assignment, totalViolations: int):
        placedHospitals = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.HOSPITAL:
                placedHospitals.append(v)
        placedIndustrials = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.INDUSTRIAL:
                placedIndustrials.append(v)
        placedSchools = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.SCHOOL:
                placedSchools.append(v)
        placedPowerPlants = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.POWER_PLANT:
                placedPowerPlants.append(v)
        placedResidentials = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.RESIDENTIAL:
                placedResidentials.append(v)

        conflicts: List[str] = []

        if len(set(assignment.values())) != len(assignment):
            duplicates = len(assignment) - len(set(assignment.values()))
            conflicts.append(
                f"[AllDiff] {duplicates} cell(s) shared by multiple locations -- "
                f"fix: increase grid size so enough unique cells are available"
            )

        for industrial in placedIndustrials:
            for school in placedSchools:
                if self.areAdjacent(industrial, school):
                    ir, ic = self.rowColCache[industrial]
                    sr, sc = self.rowColCache[school]
                    conflicts.append(
                        f"[Rule 1 -- AdjProhibition] Industrial at ({ir},{ic}) is adjacent to "
                        f"School at ({sr},{sc}) -- fix: increase numIndustrial margin or reduce "
                        f"numSchools so separation is achievable on this grid"
                    )
            for hospital in placedHospitals:
                if self.areAdjacent(industrial, hospital):
                    ir, ic = self.rowColCache[industrial]
                    hr, hc = self.rowColCache[hospital]
                    conflicts.append(
                        f"[Rule 1 -- AdjProhibition] Industrial at ({ir},{ic}) is adjacent to "
                        f"Hospital at ({hr},{hc}) -- fix: widen I-domain margin or increase grid size"
                    )

        for powerPlant in placedPowerPlants:
            if placedIndustrials and \
               min(self.manhattanDistance(powerPlant, i) for i in placedIndustrials) > self.powerMaxHops:
                pr, pc = self.rowColCache[powerPlant]
                conflicts.append(
                    f"[Rule 3 -- PowerProximity] Power Plant at ({pr},{pc}) has no Industrial "
                    f"within {self.powerMaxHops} hops -- "
                    f"fix: increase numIndustrial or reduce numPowerPlants"
                )

        uncoveredResidentials = 0
        for residential in placedResidentials:
            if placedHospitals and \
               min(self.manhattanDistance(residential, h) for h in placedHospitals) > self.residentMaxHops:
                uncoveredResidentials += 1
        if uncoveredResidentials:
            conflicts.append(
                f"[Rule 2 -- ResidentCoverage] {uncoveredResidentials} Residential node(s) are more than "
                f"{self.residentMaxHops} hops from any Hospital -- "
                f"fix: add 1 more Hospital or reduce numResidential"
            )

        placedDepots = []
        for k, v in assignment.items():
            if self.variableType[k] == LocationType.AMBULANCE_DEPOT:
                placedDepots.append(v)
        for depot in placedDepots:
            if placedHospitals and \
               min(self.manhattanDistance(depot, h) for h in placedHospitals) > self.depotMaxHops:
                dr, dc = self.rowColCache[depot]
                conflicts.append(
                    f"[Rule 4 -- DepotProximity] Depot at ({dr},{dc}) has no Hospital within "
                    f"{self.depotMaxHops} hops -- "
                    f"fix: increase numHospitals or reduce depotMaxHops threshold"
                )

        if not conflicts:
            conflicts.append(
                f"Minimum-violation solution: {totalViolations} violation(s) -- "
                f"no specific rule violation detected in final scan (may be AllDiff only)"
            )

        self.lastConflicts = conflicts

    def minimumViolationSolution(self, numRestarts: int = 30):
        return self.findMinimumViolationSolution(numRestarts=numRestarts)

    def applyAssignment(self, assignment: Assignment):
        self.city.resetLocations()
        for var, nodeId in assignment.items():
            locationType = self.variableType[var]
            self.city.setLocationType(nodeId, locationType)
            if locationType == LocationType.RESIDENTIAL:
                self.city.setPopulationDensity(nodeId, self.random.uniform(0.45, 1.0))
            elif locationType in (LocationType.INDUSTRIAL, LocationType.SCHOOL, LocationType.HOSPITAL):
                self.city.setPopulationDensity(nodeId, self.random.uniform(0.20, 0.70))
            else:
                self.city.setPopulationDensity(nodeId, self.random.uniform(0.05, 0.35))

    def solve(self, maxSteps: int = 25000, timeLimit: float = 10.0):
        if not self.runAC3():
            return CSPResult(
                False,
                conflicts=self.lastConflicts,
                message="AC-3 detected inconsistency -- no valid layout possible with current config",
            )

        self.searchDeadline = time.time() + timeLimit
        firstTierRemaining = list(self.tieredVars[0])
        result = self.backtrack({}, 0, firstTierRemaining, [maxSteps], [False])

        if result is not None:
            self.applyAssignment(result)
            debugPrintAssignment(result, self)
            return CSPResult(
                True,
                assignment=result,
                message="CSP solved via backtracking (MRV + LCV + MAC)",
            )

        fallbackResult, violations = self.findMinimumViolationSolution(numRestarts=30)
        if violations == 0 and self.checkAllConstraints(fallbackResult):
            self.applyAssignment(fallbackResult)
            debugPrintAssignment(fallbackResult, self)
            return CSPResult(
                True,
                assignment=fallbackResult,
                message="CSP solved via minimum-violation fallback (0 violations)",
            )

        conflicts = self.lastConflicts or [
            "No valid layout found within time/step limits -- try a larger grid or fewer constraints."
        ]
        return CSPResult(False, conflicts=conflicts, message="All CSP phases exhausted")