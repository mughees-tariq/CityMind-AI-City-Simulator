import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional

from city.constants import LocationType
from city.graph import CityGraph
import config


@dataclass
class AmbulanceResult:
    positions: List[int]
    worstCaseDistance: float
    generations: int
    message: str


class AmbulancePlacementGA:

    def __init__(self, city: CityGraph, seed: Optional[int] = 42):
        self.city = city
        self.random = random.Random(seed)
        self.distanceCache: Dict[int, Dict[int, float]] = {}

    def getCandidateNodes(self):
        nonResidential = []
        for nid, node in self.city.nodes.items():
            if node.accessible and node.locationType != LocationType.RESIDENTIAL:
                nonResidential.append(nid)
        if len(nonResidential) >= config.numAmbulances:
            return nonResidential
        result = []
        for nid, node in self.city.nodes.items():
            if node.accessible:
                result.append(nid)
        return result

    def getResidentialNodes(self):
        return self.city.getNodesByType(LocationType.RESIDENTIAL)

    def precomputeDistances(self, candidates: List[int]):
        self.distanceCache = {}
        for node in candidates:
            self.distanceCache[node] = self.city.dijkstraDistances(node)

    def randomChromosome(self, candidates: List[int]):
        return self.random.sample(candidates, config.numAmbulances)

    def worstCaseDistance(self, chromosome: List[int], residentialNodes: List[int]):
        worst = 0.0
        for residentialNode in residentialNodes:
            nearestDist = min(self.distanceCache[amb].get(residentialNode, math.inf) for amb in chromosome)
            worst = max(worst, nearestDist)
        return worst

    def fitness(self, chromosome: List[int], residentialNodes: List[int]):
        worst = self.worstCaseDistance(chromosome, residentialNodes)
        if math.isinf(worst):
            return -1_000_000.0
        return -worst

    def tournamentSelect(self, population: List[List[int]], residentialNodes: List[int], tournamentSize: int = 3):
        sample = self.random.sample(population, min(tournamentSize, len(population)))
        result = max(sample, key=lambda chromosome: self.fitness(chromosome, residentialNodes))
        return result[:]

    def crossover(self, parent1: List[int], parent2: List[int], candidates: List[int]):
        child = []
        for a, b in zip(parent1, parent2):
            child.append(a if self.random.random() < 0.5 else b)
        unique = []
        for gene in child:
            if gene not in unique:
                unique.append(gene)
        while len(unique) < config.numAmbulances:
            newGene = self.random.choice(candidates)
            if newGene not in unique:
                unique.append(newGene)
        return unique[:config.numAmbulances]

    def mutate(self, chromosome: List[int], candidates: List[int], mutationRate: float = 0.10):
        result = chromosome[:]
        for i in range(len(result)):
            if self.random.random() < mutationRate:
                options = [n for n in candidates if n not in result]
                if options:
                    result[i] = self.random.choice(options)
        return result

    def run(self, populationSize: int = 60, numGenerations: int = 100):
        candidates = self.getCandidateNodes()
        residentialNodes = self.getResidentialNodes()

        if len(candidates) < config.numAmbulances:
            return AmbulanceResult([], math.inf, 0, "Not enough accessible nodes for ambulances")
        if not residentialNodes:
            return AmbulanceResult([], math.inf, 0, "No residential nodes exist to cover")

        self.precomputeDistances(candidates)
        population = []
        for _ in range(populationSize):
            population.append(self.randomChromosome(candidates))

        for _ in range(numGenerations):
            population.sort(key=lambda chromosome: self.fitness(chromosome, residentialNodes), reverse=True)
            nextPopulation = [population[0][:], population[1][:]]
            while len(nextPopulation) < populationSize:
                parent1 = self.tournamentSelect(population, residentialNodes)
                parent2 = self.tournamentSelect(population, residentialNodes)
                child = self.crossover(parent1, parent2, candidates)
                child = self.mutate(child, candidates)
                nextPopulation.append(child)
            population = nextPopulation

        bestChromosome = max(population, key=lambda chromosome: self.fitness(chromosome, residentialNodes))
        worstDist = self.worstCaseDistance(bestChromosome, residentialNodes)
        self.city.ambulancePositions = bestChromosome[:]

        coverageRadii = []
        for amb in bestChromosome:
            ambWorstCoverage = 0.0
            for residentialNode in residentialNodes:
                allDistances = [self.distanceCache[a].get(residentialNode, math.inf) for a in bestChromosome]
                minDist = min(allDistances)
                closestAmb = bestChromosome[allDistances.index(minDist)]
                if closestAmb == amb and not math.isinf(minDist):
                    ambWorstCoverage = max(ambWorstCoverage, minDist)
            coverageRadii.append(ambWorstCoverage if ambWorstCoverage > 0 else worstDist / len(bestChromosome))
        self.city.ambulanceCoverageRadii = coverageRadii

        if math.isinf(worstDist):
            return AmbulanceResult(
                bestChromosome, worstDist, numGenerations,
                "WARNING: Ambulance GA completed but some residential nodes are unreachable "
                "due to road blockages -- coverage is partial only.",
            )
        return AmbulanceResult(bestChromosome, worstDist, numGenerations, "Ambulance GA completed")