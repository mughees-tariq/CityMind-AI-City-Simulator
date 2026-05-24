import heapq
import math
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from city.constants import LocationType
from city.graph import CityGraph


@dataclass
class RoadNetworkResult:
    success: bool
    roadCount: int
    totalCost: float
    primaryHospital: Optional[int]
    primaryDepot: Optional[int]
    message: str


class UnionFind:

    def __init__(self, items: List[int]):
        self.parent = {x: x for x in items}
        self.rank = {x: 0 for x in items}

    def find(self, x: int):
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, a: int, b: int):
        rootA, rootB = self.find(a), self.find(b)
        if rootA == rootB:
            return False
        if self.rank[rootA] < self.rank[rootB]:
            self.parent[rootA] = rootB
        elif self.rank[rootA] > self.rank[rootB]:
            self.parent[rootB] = rootA
        else:
            self.parent[rootB] = rootA
            self.rank[rootA] += 1
        return True


class RoadNetworkBuilder:

    def __init__(self, city: CityGraph):
        self.city = city

    def choosePrimaryDepot(self):
        depots = self.city.getNodesByType(LocationType.AMBULANCE_DEPOT)
        if not depots:
            return None
        hospitals = self.city.getNodesByType(LocationType.HOSPITAL)
        if not hospitals:
            return depots[0]
        bestDepot = None
        bestDist = math.inf
        for depot in depots:
            distances = self.city.dijkstraDistances(depot)
            nearestHospDist = min(distances.get(h, math.inf) for h in hospitals)
            if nearestHospDist < bestDist:
                bestDist = nearestHospDist
                bestDepot = depot
        return bestDepot

    def choosePrimaryHospital(self):
        hospitals = self.city.getNodesByType(LocationType.HOSPITAL)
        if not hospitals:
            return None
        depot = self.choosePrimaryDepot()
        if depot is None:
            return hospitals[0]
        distances = self.city.dijkstraDistances(depot)
        result = min(hospitals, key=lambda nid: distances.get(nid, math.inf))
        return result

    def build(self):
        self.city.removeAllRoads()
        sortedEdges = sorted(self.city.candidateGridEdges(), key=lambda e: e[2])
        uf = UnionFind(self.city.allNodeIds())
        mstEdges: List[Tuple[int, int, float]] = []
        for u, v, cost in sortedEdges:
            if uf.union(u, v):
                self.city.addRoad(u, v, cost)
                mstEdges.append((u, v, cost))

        primaryHospital = self.choosePrimaryHospital()
        primaryDepot = self.choosePrimaryDepot()
        if primaryHospital is None or primaryDepot is None:
            return RoadNetworkResult(
                False, len(self.city.currentEdges()), self.computeTotalCost(),
                primaryHospital, primaryDepot,
                "Cannot enforce redundancy: primary hospital or depot is missing",
            )

        addedEdges = self.enforceRedundantRoutes(primaryHospital, primaryDepot)

        if addedEdges == 0:
            return RoadNetworkResult(
                False, len(self.city.currentEdges()), self.computeTotalCost(),
                primaryHospital, primaryDepot,
                "CRITICAL: MST built but no alternate route found between hospital and depot "
                "-- biconnectivity could not be enforced. Grid may be too constrained.",
            )

        if self.city.redundancyEdges and addedEdges > 0:
            msg = (
                f"Road network built with MST plus {addedEdges} redundancy edge(s) -- "
                f"biconnectivity enforced via Menger path using non-MST edges "
                f"(longer path chosen to guarantee hospital-depot connectivity)"
            )
        else:
            msg = f"Road network built with MST plus {addedEdges} redundancy edges"

        return RoadNetworkResult(
            True, len(self.city.currentEdges()), self.computeTotalCost(),
            primaryHospital, primaryDepot, msg,
        )

    def computeTotalCost(self):
        result = sum(cost for _, _, cost, _ in self.city.currentEdges())
        return result

    def pathInCurrentRoads(self, start: int, goal: int):
        queue = deque([start])
        parent: Dict[int, Optional[int]] = {start: None}
        while queue:
            u = queue.popleft()
            if u == goal:
                break
            for v in self.city.roads[u]:
                if v not in parent:
                    parent[v] = u
                    queue.append(v)
        if goal not in parent:
            return []
        path = []
        current: Optional[int] = goal
        while current is not None:
            path.append(current)
            current = parent[current]
        result = list(reversed(path))
        return result

    def enforceRedundantRoutes(self, start: int, goal: int):
        treePath = self.pathInCurrentRoads(start, goal)
        treePathEdges = set()
        for a, b in zip(treePath, treePath[1:]):
            treePathEdges.add(tuple(sorted((a, b))))

        existingRoads = set()
        for u, v, cost, _ in self.city.currentEdges():
            existingRoads.add(tuple(sorted((u, v))))

        dist = {nid: math.inf for nid in self.city.nodes}
        parent: Dict[int, Optional[int]] = {start: None}
        dist[start] = 0.0
        heap = [(0.0, start)]

        candidateNeighbors: Dict[int, List[Tuple[int, float]]] = {nid: [] for nid in self.city.nodes}
        for u, v, cost in self.city.candidateGridEdges():
            key = tuple(sorted((u, v)))
            if key in treePathEdges:
                continue
            penalizedCost = cost if key in existingRoads else cost * 20
            candidateNeighbors[u].append((v, penalizedCost))
            candidateNeighbors[v].append((u, penalizedCost))

        while heap:
            d, u = heapq.heappop(heap)
            if u == goal:
                break
            if d > dist[u]:
                continue
            for v, cost in candidateNeighbors[u]:
                newDist = d + cost
                if newDist < dist[v]:
                    dist[v] = newDist
                    parent[v] = u
                    heapq.heappush(heap, (newDist, v))

        if goal not in parent:
            return 0

        alternatePath = []
        current: Optional[int] = goal
        while current is not None:
            alternatePath.append(current)
            current = parent[current]
        alternatePath.reverse()

        addedCount = 0
        for a, b in zip(alternatePath, alternatePath[1:]):
            if b not in self.city.roads[a]:
                self.city.addRoad(a, b)
                self.city.redundancyEdges.add(tuple(sorted((a, b))))
                addedCount += 1
        return addedCount

    def countEdgeDisjointPaths(self, start: int, goal: int):
        def bfsPath(adj):
            parent = {start: None}
            queue = deque([start])
            while queue:
                u = queue.popleft()
                if u == goal:
                    break
                for v in adj.get(u, []):
                    if v not in parent:
                        parent[v] = u
                        queue.append(v)
            if goal not in parent:
                return []
            path = []
            node = goal
            while node is not None:
                path.append(node)
                node = parent[node]
            result = list(reversed(path))
            return result

        adj: Dict[int, List[int]] = {}
        for u, v, _, blocked in self.city.currentEdges():
            if not blocked:
                adj.setdefault(u, []).append(v)
                adj.setdefault(v, []).append(u)

        count = 0
        for _ in range(2):
            path = bfsPath(adj)
            if not path:
                break
            count += 1
            for a, b in zip(path, path[1:]):
                adj[a] = [x for x in adj.get(a, []) if x != b]
                adj[b] = [x for x in adj.get(b, []) if x != a]
        return count

    def hospitalDepotStillBiconnected(self):
        hospital = self.choosePrimaryHospital()
        depot = self.choosePrimaryDepot()
        if hospital is None or depot is None:
            return False
        result = self.countEdgeDisjointPaths(hospital, depot) >= 2
        return result