import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from city.constants import LocationType
from city.graph import CityGraph


@dataclass
class RouteState:
    currentPosition: Optional[int] = None
    remainingTargets: List[int] = field(default_factory=list)
    visitedTargets: List[int] = field(default_factory=list)
    currentPath: List[int] = field(default_factory=list)
    currentTarget: Optional[int] = None
    totalTravelCost: float = 0.0
    deferredTargets: List[int] = field(default_factory=list)


class EmergencyRouter:

    def __init__(self, city: CityGraph):
        self.city = city
        self.state = RouteState()

    def findDefaultStart(self):
        depots = self.city.getNodesByType(LocationType.AMBULANCE_DEPOT)
        if depots:
            return depots[0]
        return None

    def start(self, civilianTargets: List[int], startNode: Optional[int] = None):
        if startNode is None:
            startNode = self.findDefaultStart()
        self.state = RouteState(
            currentPosition=startNode,
            remainingTargets=list(civilianTargets),
            visitedTargets=[],
            currentPath=[],
            currentTarget=None,
            totalTravelCost=0.0,
            deferredTargets=[],
        )
        self.planNextLeg()
        return self.state

    def findNearestTarget(self):
        if self.state.currentPosition is None:
            return None, [], math.inf
        bestTarget = None
        bestPath: List[int] = []
        bestCost = math.inf
        for target in self.state.remainingTargets:
            path, cost = self.city.shortestPath(self.state.currentPosition, target)
            if path and cost < bestCost:
                bestTarget = target
                bestPath = path
                bestCost = cost
        return bestTarget, bestPath, bestCost

    def isTargetReachable(self, target: int):
        start = self.state.currentPosition
        if start is None:
            return False
        visited = {start}
        queue = [start]
        while queue:
            current = queue.pop()
            if current == target:
                return True
            for neighbor in self.city.roads[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        return False

    def planNextLeg(self):
        if self.state.deferredTargets and self.state.currentPosition is not None:
            recovered = []
            stillDeferred = []
            for target in self.state.deferredTargets:
                path, cost = self.city.shortestPath(self.state.currentPosition, target)
                if path and not math.isinf(cost):
                    recovered.append(target)
                else:
                    stillDeferred.append(target)
            self.state.remainingTargets.extend(recovered)
            self.state.deferredTargets = stillDeferred

        if not self.state.remainingTargets:
            self.state.currentTarget = None
            self.state.currentPath = []
            result = len(self.state.deferredTargets) == 0
            return result

        target, path, cost = self.findNearestTarget()
        if target is None or not path:
            return False

        self.state.currentTarget = target
        self.state.currentPath = path
        return True

    def currentPathHasBlockedRoad(self):
        path = self.state.currentPath
        for u, v in zip(path, path[1:]):
            if self.city.isRoadBlocked(u, v):
                return True
        return False

    def reroute(self):
        result = self.planNextLeg()
        return result

    def skipUnreachableTargets(self):
        if self.state.currentPosition is None:
            return 0
        permanentlyDropped = 0
        stillReachable = []
        for target in self.state.remainingTargets:
            path, cost = self.city.shortestPath(self.state.currentPosition, target)
            if path and not math.isinf(cost):
                stillReachable.append(target)
            elif self.isTargetReachable(target):
                self.state.deferredTargets.append(target)
            else:
                permanentlyDropped += 1
        self.state.remainingTargets = stillReachable
        if not stillReachable:
            self.planNextLeg()
        return permanentlyDropped

    def advanceOneStep(self):
        if self.state.currentPosition is None:
            return "Router has no starting position"

        if self.currentPathHasBlockedRoad():
            if not self.reroute():
                return "Reroute failed: no currently available path"

        if not self.state.currentPath:
            if not self.state.remainingTargets and not self.state.deferredTargets:
                return "All civilians rescued -- mission complete"
            if not self.state.remainingTargets and self.state.deferredTargets:
                return f"No reachable targets -- {len(self.state.deferredTargets)} deferred target(s) waiting for route to clear"
            skipped = self.skipUnreachableTargets()
            if self.state.currentPath:
                msg = f"Continuing to target {self.state.currentTarget}"
                if skipped:
                    msg = f"Dropped {skipped} truly isolated target(s); {msg}"
                if self.state.deferredTargets:
                    msg += f" ({len(self.state.deferredTargets)} deferred)"
                return msg
            return "No current path to any remaining target"

        if len(self.state.currentPath) == 1:
            target = self.state.currentPath[0]
            if target in self.state.remainingTargets:
                self.state.remainingTargets.remove(target)
                if target not in self.state.visitedTargets:
                    self.state.visitedTargets.append(target)
            self.state.currentPath = []
            self.planNextLeg()
            if not self.state.remainingTargets and not self.state.deferredTargets:
                return f"Reached civilian target {target} - all civilians rescued, mission complete"
            return f"Reached target {target}"

        nextNode = self.state.currentPath[1]
        stepCost = self.city.effectiveCost(self.state.currentPosition, nextNode)
        if math.isinf(stepCost):
            if self.reroute():
                return "Road became impassable; route recalculated"
            return "Road became impassable; no route found"

        self.state.currentPosition = nextNode
        self.state.totalTravelCost += stepCost
        self.state.currentPath = self.state.currentPath[1:]

        if self.state.currentPosition == self.state.currentTarget:
            target = self.state.currentPosition
            if target in self.state.remainingTargets:
                self.state.remainingTargets.remove(target)
                self.state.visitedTargets.append(target)
            self.planNextLeg()
            if not self.state.remainingTargets and not self.state.deferredTargets:
                return f"Reached civilian target {target} - all civilians rescued, mission complete"
            return f"Reached civilian target {target}"

        return f"Moved to node {nextNode}"