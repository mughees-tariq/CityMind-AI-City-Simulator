import math
import random
from typing import Optional

from algorithms.ambulance_ga import AmbulancePlacementGA
from algorithms.crime_risk import CrimeRiskPipeline
from algorithms.csp_layout import CityLayoutCSP
from algorithms.road_network import RoadNetworkBuilder, RoadNetworkResult
from algorithms.routing import EmergencyRouter
from city.constants import LocationType
from city.graph import CityGraph
import config
from simulation.event_log import EventLog


class CityMindSimulator:

    def __init__(self, rows: int = None, cols: int = None,
                 seed: Optional[int] = None, maxTicks: int = None):
        rows = rows if rows is not None else config.defaultRows
        cols = cols if cols is not None else config.defaultCols
        seed = seed if seed is not None else config.defaultRandomSeed
        maxTicks = maxTicks if maxTicks is not None else config.simulationTicks

        self.city = CityGraph(rows, cols)
        self.log = EventLog()
        self.random = random.Random(seed)
        self.seed = seed
        self.router: Optional[EmergencyRouter] = None
        self.roadBuilder: Optional[RoadNetworkBuilder] = None
        self.tick = 0
        self.maxTicks: int = maxTicks

    def runChallenge1Layout(self):
        solver = CityLayoutCSP(self.city, seed=self.seed)
        result = solver.solve()
        if result.success:
            self.log.add("C1", f"CSP solved: {len(result.assignment)} locations placed")
            return True

        seen = set()
        for conflict in result.conflicts:
            if conflict not in seen:
                self.log.add("C1", f"Constraint violated: {conflict}")
                seen.add(conflict)

        self.log.add("C1", "CSP backtracking exhausted -- running minimum-violation solver as fallback...")
        fallbackAssignment, violations = solver.minimumViolationSolution()
        solver.applyAssignment(fallbackAssignment)

        if violations == 0:
            self.log.add("C1", "Minimum-violation solver: valid layout found with 0 violations -- continuing pipeline")
            return True

        for conflict in solver.lastConflicts:
            self.log.add("C1", conflict)

        self.log.add("C1", f"Minimum-violation solution: {violations} violation(s) remain -- partial layout applied, pipeline continues")
        return True

    def runChallenge2Roads(self):
        builder = RoadNetworkBuilder(self.city)
        self.roadBuilder = builder
        result = builder.build()
        self.log.add("C2", f"{result.message}; roads={result.roadCount}; cost={result.totalCost:.2f}")
        self.log.add("C2", f"Primary hospital=node {result.primaryHospital}; primary depot=node {result.primaryDepot}")
        return result.success

    def runChallenge5Risk(self):
        pipeline = CrimeRiskPipeline(self.city, seed=self.seed)
        result = pipeline.run()
        self.log.add(
            "C5",
            f"Risk updated; best_clf={result.bestClassifier} (F1={result.bestF1:.2f}); "
            f"counts={result.labelCounts}; police={result.policeAllocation}",
        )
        return True

    def runChallenge3Ambulances(self):
        ga = AmbulancePlacementGA(self.city, seed=self.seed)
        result = ga.run()
        if result.positions:
            if math.isinf(result.worstCaseDistance):
                self.log.add(
                    "C3",
                    f"Ambulances placed at {result.positions}; worst-case distance=inf -- {result.message}",
                )
            else:
                self.log.add(
                    "C3",
                    f"Ambulances placed at {result.positions}; worst-case distance={result.worstCaseDistance:.2f}",
                )
            return True
        self.log.add("C3", result.message)
        return False

    def chooseDefaultCivilians(self):
        residentials = self.city.getNodesByType(LocationType.RESIDENTIAL)
        if len(residentials) <= 4:
            targets = residentials[:]
        else:
            targets = self.random.sample(residentials, 4)
        self.city.civilianTargets = targets[:]
        return targets

    def runChallenge4Routing(self):
        targets = self.chooseDefaultCivilians()
        if not targets:
            self.log.add("C4", "No civilian targets available")
            return False
        self.router = EmergencyRouter(self.city)
        state = self.router.start(targets)
        if state.currentPath:
            self.log.add("C4", f"Initial route planned to target {state.currentTarget}; path length={len(state.currentPath)}")
            return True
        skipped = self.router.skipUnreachableTargets()
        if skipped > 0 and self.router.state.currentPath:
            self.log.add("C4", f"Skipped {skipped} unreachable target(s); route planned to target {self.router.state.currentTarget}; path length={len(self.router.state.currentPath)}")
            return True
        self.log.add("C4", "Initial route could not be planned -- all targets unreachable")
        return False

    def runInitialPipeline(self):
        self.log.add("INIT", f"CityMind started with grid {self.city.rows}x{self.city.cols}")
        steps = [
            self.runChallenge1Layout,
            self.runChallenge2Roads,
            self.runChallenge5Risk,
            self.runChallenge3Ambulances,
            self.runChallenge4Routing,
        ]
        for step in steps:
            if not step():
                return False
        return True

    def randomlyBlockRoad(self):
        openEdges = [(u, v) for u, v, _, blocked in self.city.currentEdges() if not blocked]
        if not openEdges:
            return None
        nonBridgeEdges = [e for e in openEdges if not self.isBridgeEdge(e[0], e[1])]
        if not nonBridgeEdges:
            return None
        u, v = self.random.choice(nonBridgeEdges)
        self.city.blockRoad(u, v)
        return u, v

    def isBridgeEdge(self, u: int, v: int):
        openAdjacency: dict[int, list[int]] = {}
        for a, b, _, blocked in self.city.currentEdges():
            if blocked:
                continue
            if (a == u and b == v) or (a == v and b == u):
                continue
            openAdjacency.setdefault(a, []).append(b)
            openAdjacency.setdefault(b, []).append(a)
        visited = {u}
        queue = [u]
        while queue:
            current = queue.pop()
            for neighbor in openAdjacency.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        result = v not in visited
        return result

    def runTick(self):
        if self.router is None:
            return False
        if self.maxTicks > 0 and self.tick >= self.maxTicks:
            return False

        self.tick += 1
        tag = f"T{self.tick}"

        blocked = self.randomlyBlockRoad()
        if blocked is not None:
            self.log.add(tag, f"Road blocked between {blocked[0]} and {blocked[1]}")
            if self.roadBuilder is not None and not self.roadBuilder.hospitalDepotStillBiconnected():
                self.log.add(tag, "CRITICAL: hospital-depot biconnectivity lost -- fewer than 2 edge-disjoint paths remain")
            if self.router.currentPathHasBlockedRoad():
                if self.router.reroute():
                    self.log.add(tag, "Blocked road affected current route; A* reroute completed")
                else:
                    dropped = self.router.skipUnreachableTargets()
                    numDeferred = len(self.router.state.deferredTargets)
                    if dropped > 0 and self.router.state.currentPath:
                        self.log.add(tag, f"WARNING: {dropped} civilian target(s) truly isolated (no road) -- permanently dropped; rerouting to next reachable target")
                    elif dropped > 0:
                        self.log.add(tag, f"WARNING: {dropped} civilian target(s) truly isolated -- dropped; no further targets remain")
                    elif numDeferred > 0 and self.router.state.currentPath:
                        self.log.add(tag, f"{numDeferred} target(s) deferred (blocked path, not isolated) -- will retry after rescuing other civilians")
                    else:
                        self.log.add(tag, "Blocked road affected current route; no route available to any remaining target")

        midpoint = max(1, self.maxTicks // 2) if self.maxTicks > 0 else 10
        if self.tick == midpoint:
            self.log.add(tag, "Mid-simulation risk refresh started")
            self.runChallenge5Risk()
            self.runChallenge3Ambulances()

        maxStepsPerTick = 5
        for _ in range(maxStepsPerTick):
            msg = self.router.advanceOneStep()
            self.log.add(tag, msg)
            if "Reached" in msg or "complete" in msg or "failed" in msg:
                break
        return True

    def runFullSimulation(self):
        if self.router is None:
            if not self.runInitialPipeline():
                return
        if self.maxTicks > 0:
            while self.tick < self.maxTicks:
                self.runTick()
            self.log.add("END", f"{self.maxTicks}-step simulation finished")
        else:
            cap = 9999
            while cap > 0:
                if not self.runTick():
                    break
                if self.router and ("complete" in (self.log.entries[-1][1] if self.log.entries else "")):
                    break
                cap -= 1
            self.log.add("END", f"Simulation finished after {self.tick} tick(s)")