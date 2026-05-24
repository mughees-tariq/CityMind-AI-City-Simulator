import heapq
import math
from typing import Dict, List, Optional, Tuple

import config
from city.constants import LocationType
from city.node import CityNode


class CityGraph:

    def __init__(self, rows: int, cols: int):
        self.rows = rows
        self.cols = cols
        self.nodes: Dict[int, CityNode] = {}
        self.roads: Dict[int, Dict[int, Dict[str, float | bool]]] = {}
        self.ambulancePositions: List[int] = []
        self.ambulanceCoverageRadii: List[float] = []
        self.civilianTargets: List[int] = []
        self.policeAllocation: Dict[str, int] = {}
        self.riskLabels: Dict[int, str] = {}
        self.redundancyEdges: set = set()
        for r in range(rows):
            for c in range(cols):
                nid = self.nodeId(r, c)
                self.nodes[nid] = CityNode(nodeId=nid, row=r, col=c)
                self.roads[nid] = {}

    def nodeId(self, row: int, col: int):
        return row * self.cols + col

    def rowCol(self, nid: int):
        return divmod(nid, self.cols)

    def inBounds(self, row: int, col: int):
        return 0 <= row < self.rows and 0 <= col < self.cols

    def allNodeIds(self):
        return list(self.nodes.keys())

    def getNode(self, nid: int):
        return self.nodes[nid]

    def getNodesByType(self, locationType: LocationType):
        result = []
        for nid, node in self.nodes.items():
            if node.locationType == locationType:
                result.append(nid)
        return result

    def manhattan(self, a: int, b: int):
        ar, ac = self.rowCol(a)
        br, bc = self.rowCol(b)
        return abs(ar - br) + abs(ac - bc)

    def gridNeighbors(self, nid: int):
        r, c = self.rowCol(nid)
        result = []
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if self.inBounds(nr, nc):
                result.append(self.nodeId(nr, nc))
        return result

    def resetLocations(self):
        for node in self.nodes.values():
            node.locationType = LocationType.EMPTY
            node.populationDensity = 0.0
            node.riskIndex = 0.0
            node.accessible = True
        self.ambulancePositions.clear()
        self.ambulanceCoverageRadii.clear()
        self.civilianTargets.clear()
        self.policeAllocation.clear()
        self.riskLabels.clear()
        self.redundancyEdges.clear()

    def setLocationType(self, nid: int, locationType: LocationType):
        self.nodes[nid].locationType = locationType

    def setPopulationDensity(self, nid: int, value: float):
        self.nodes[nid].populationDensity = max(0.0, min(1.0, float(value)))

    def updateRisk(self, nid: int, riskValue: float, label: Optional[str] = None):
        self.nodes[nid].riskIndex = max(0.0, min(1.0, float(riskValue)))
        if label is not None:
            self.riskLabels[nid] = label

    def setAccessible(self, nid: int, accessible: bool):
        self.nodes[nid].accessible = accessible

    def baseRoadCost(self, u: int, v: int):
        if (self.nodes[u].locationType == LocationType.RESIDENTIAL
                or self.nodes[v].locationType == LocationType.RESIDENTIAL):
            return 0.8
        return 1.0

    def addRoad(self, u: int, v: int, cost: Optional[float] = None):
        if cost is None:
            cost = self.baseRoadCost(u, v)
        self.roads[u][v] = {"cost": float(cost), "blocked": False}
        self.roads[v][u] = {"cost": float(cost), "blocked": False}

    def removeAllRoads(self):
        for nid in self.nodes:
            self.roads[nid] = {}

    def blockRoad(self, u: int, v: int):
        if v not in self.roads.get(u, {}):
            return False
        self.roads[u][v]["blocked"] = True
        self.roads[v][u]["blocked"] = True
        return True

    def unblockRoad(self, u: int, v: int):
        if v not in self.roads.get(u, {}):
            return False
        self.roads[u][v]["blocked"] = False
        self.roads[v][u]["blocked"] = False
        return True

    def isRoadBlocked(self, u: int, v: int):
        if v not in self.roads.get(u, {}):
            return True
        return bool(self.roads[u][v]["blocked"])

    def currentEdges(self):
        edges = []
        seen = set()
        for u, neighbors in self.roads.items():
            for v, data in neighbors.items():
                key = tuple(sorted((u, v)))
                if key not in seen:
                    seen.add(key)
                    edges.append((u, v, float(data["cost"]), bool(data["blocked"])))
        return edges

    def candidateGridEdges(self):
        edges = []
        seen = set()
        for u in self.allNodeIds():
            if not self.nodes[u].accessible:
                continue
            for v in self.gridNeighbors(u):
                if not self.nodes[v].accessible:
                    continue
                key = tuple(sorted((u, v)))
                if key not in seen:
                    seen.add(key)
                    edges.append((u, v, self.baseRoadCost(u, v)))
        return edges

    def effectiveCost(self, u: int, v: int):
        if v not in self.roads.get(u, {}):
            return math.inf
        if self.roads[u][v]["blocked"]:
            return math.inf
        if not self.nodes[u].accessible or not self.nodes[v].accessible:
            return math.inf
        baseCost = float(self.roads[u][v]["cost"])
        destinationRisk = self.nodes[v].riskIndex
        return baseCost * (1.0 + config.riskCostMultiplier * destinationRisk)

    def heuristic(self, a: int, b: int):
        return self.manhattan(a, b) * 0.8

    def shortestPath(self, start: int, goal: int):
        if start == goal:
            return [start], 0.0
        openHeap = [(self.heuristic(start, goal), 0.0, start)]
        cameFrom: Dict[int, Optional[int]] = {start: None}
        gScore: Dict[int, float] = {start: 0.0}
        closed = set()
        while openHeap:
            _, currentG, current = heapq.heappop(openHeap)
            if current in closed:
                continue
            closed.add(current)
            if current == goal:
                path = []
                node = current
                while node is not None:
                    path.append(node)
                    node = cameFrom[node]
                path.reverse()
                return path, currentG
            for neighbor in self.roads[current]:
                cost = self.effectiveCost(current, neighbor)
                if math.isinf(cost):
                    continue
                newG = currentG + cost
                if newG < gScore.get(neighbor, math.inf):
                    gScore[neighbor] = newG
                    cameFrom[neighbor] = current
                    heapq.heappush(openHeap, (newG + self.heuristic(neighbor, goal), newG, neighbor))
        return [], math.inf

    def dijkstraDistances(self, start: int):
        dist = {nid: math.inf for nid in self.nodes}
        dist[start] = 0.0
        heap = [(0.0, start)]
        visited = set()
        while heap:
            d, u = heapq.heappop(heap)
            if u in visited:
                continue
            visited.add(u)
            for v in self.roads[u]:
                cost = self.effectiveCost(u, v)
                if math.isinf(cost):
                    continue
                newDist = d + cost
                if newDist < dist[v]:
                    dist[v] = newDist
                    heapq.heappush(heap, (newDist, v))
        return dist