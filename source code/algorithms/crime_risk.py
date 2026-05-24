import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from city.constants import LocationType, RiskLevel, riskValue
from city.graph import CityGraph
import config


@dataclass
class CrimeRiskResult:
    clusterCount: int
    labelCounts: Dict[str, int]
    policeAllocation: Dict[str, int]
    bestClassifier: str
    bestF1: float
    message: str


class ManualStandardScaler:

    def fitTransform(self, featureMatrix: np.ndarray):
        self.mean = featureMatrix.mean(axis=0)
        self.std = featureMatrix.std(axis=0)
        self.std[self.std == 0] = 1.0
        result = (featureMatrix - self.mean) / self.std
        return result


def kmeansPlusPlusInit(featureMatrix: np.ndarray, numClusters: int, rng: np.random.Generator):
    numSamples = featureMatrix.shape[0]
    firstIdx = rng.integers(0, numSamples)
    centroids = [featureMatrix[firstIdx]]
    for _ in range(1, numClusters):
        distances = np.array([min(np.sum((x - c) ** 2) for c in centroids) for x in featureMatrix])
        probs = distances / distances.sum()
        cumulative = np.cumsum(probs)
        r = rng.random()
        idx = int(np.searchsorted(cumulative, r))
        centroids.append(featureMatrix[idx])
    return np.array(centroids)


def runKMeans(featureMatrix: np.ndarray, numClusters: int = 3, numInits: int = 10,
              maxIterations: int = 300, seed: int = 42):
    rng = np.random.default_rng(seed)
    bestLabels = None
    bestInertia = float("inf")
    for _ in range(numInits):
        centroids = kmeansPlusPlusInit(featureMatrix, numClusters, rng)
        for _ in range(maxIterations):
            distances = np.array([[np.sum((x - c) ** 2) for c in centroids] for x in featureMatrix])
            labels = distances.argmin(axis=1)
            newCentroids = np.array([
                featureMatrix[labels == j].mean(axis=0) if np.any(labels == j) else centroids[j]
                for j in range(numClusters)
            ])
            if np.allclose(newCentroids, centroids, atol=1e-6):
                break
            centroids = newCentroids
        inertia = sum(np.sum((featureMatrix[i] - centroids[labels[i]]) ** 2) for i in range(len(featureMatrix)))
        if inertia < bestInertia:
            bestInertia = inertia
            bestLabels = labels.copy()
    return bestLabels


def getUniqueClasses(labels: List[str]):
    return sorted(set(labels))


def labelsToInts(labels: List[str], classes: List[str]):
    mapping = {c: i for i, c in enumerate(classes)}
    result = np.array([mapping[v] for v in labels])
    return result


def intsToLabels(intArray: np.ndarray, classes: List[str]):
    result = [classes[i] for i in intArray]
    return result


def stratifiedTrainTestSplit(featureMatrix: np.ndarray, labels: List[str], testFraction: float = 0.25, seed: int = 42):
    classes = getUniqueClasses(labels)
    labelsArray = np.array(labels)
    rng = np.random.default_rng(seed)
    trainIndices = []
    testIndices = []
    for cls in classes:
        classIndices = np.where(labelsArray == cls)[0]
        rng.shuffle(classIndices)
        numTest = max(1, int(round(len(classIndices) * testFraction)))
        testIndices.extend(classIndices[:numTest].tolist())
        trainIndices.extend(classIndices[numTest:].tolist())
    return featureMatrix[trainIndices], featureMatrix[testIndices], labelsArray[trainIndices].tolist(), labelsArray[testIndices].tolist()


def computeMacroF1(trueLabels: List[str], predictedLabels: List[str]):
    classes = getUniqueClasses(trueLabels)
    f1Scores = []
    for cls in classes:
        tp = sum(1 for t, p in zip(trueLabels, predictedLabels) if t == cls and p == cls)
        fp = sum(1 for t, p in zip(trueLabels, predictedLabels) if t != cls and p == cls)
        fn = sum(1 for t, p in zip(trueLabels, predictedLabels) if t == cls and p != cls)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1Scores.append(2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0)
    if f1Scores:
        return sum(f1Scores) / len(f1Scores)
    return 0.0


class ManualDecisionTree:

    def __init__(self, maxDepth: int = None, seed: int = 42):
        self.maxDepth = maxDepth
        self.seed = seed
        self.tree = None
        self.classes = None

    def computeGini(self, labels: np.ndarray):
        n = len(labels)
        if n == 0:
            return 0.0
        counts = np.bincount(labels, minlength=len(self.classes))
        probs = counts / n
        result = 1.0 - float(np.sum(probs ** 2))
        return result

    def findBestSplit(self, featureMatrix: np.ndarray, labels: np.ndarray):
        numSamples, numFeatures = featureMatrix.shape
        bestGain = -1.0
        bestFeatureIdx = None
        bestThreshold = None
        parentGini = self.computeGini(labels)
        for featureIdx in range(numFeatures):
            for threshold in np.unique(featureMatrix[:, featureIdx]):
                leftLabels = labels[featureMatrix[:, featureIdx] <= threshold]
                rightLabels = labels[featureMatrix[:, featureIdx] > threshold]
                if len(leftLabels) == 0 or len(rightLabels) == 0:
                    continue
                gain = parentGini - (
                    len(leftLabels) / numSamples * self.computeGini(leftLabels) +
                    len(rightLabels) / numSamples * self.computeGini(rightLabels)
                )
                if gain > bestGain:
                    bestGain = gain
                    bestFeatureIdx = featureIdx
                    bestThreshold = threshold
        return bestFeatureIdx, bestThreshold

    def buildTree(self, featureMatrix: np.ndarray, labels: np.ndarray, depth: int):
        if len(np.unique(labels)) == 1 or (self.maxDepth is not None and depth >= self.maxDepth):
            return int(np.bincount(labels, minlength=len(self.classes)).argmax())
        featureIdx, threshold = self.findBestSplit(featureMatrix, labels)
        if featureIdx is None:
            return int(np.bincount(labels, minlength=len(self.classes)).argmax())
        mask = featureMatrix[:, featureIdx] <= threshold
        return (featureIdx, threshold,
                self.buildTree(featureMatrix[mask], labels[mask], depth + 1),
                self.buildTree(featureMatrix[~mask], labels[~mask], depth + 1))

    def fit(self, featureMatrix: np.ndarray, labels: List[str]):
        self.classes = getUniqueClasses(labels)
        self.tree = self.buildTree(featureMatrix, labelsToInts(labels, self.classes), 0)

    def traverseTree(self, node, sample: np.ndarray):
        if not isinstance(node, tuple):
            return node
        featureIdx, threshold, leftSubtree, rightSubtree = node
        if sample[featureIdx] <= threshold:
            return self.traverseTree(leftSubtree, sample)
        return self.traverseTree(rightSubtree, sample)

    def predict(self, featureMatrix: np.ndarray):
        result = intsToLabels(np.array([self.traverseTree(self.tree, x) for x in featureMatrix]), self.classes)
        return result


class ManualRandomForest:

    def __init__(self, numTrees: int = 100, maxDepth: int = 10, seed: int = 42):
        self.numTrees = numTrees
        self.maxDepth = maxDepth
        self.seed = seed
        self.trees = []
        self.classes = None

    def fit(self, featureMatrix: np.ndarray, labels: List[str]):
        self.classes = getUniqueClasses(labels)
        rng = np.random.default_rng(self.seed)
        numSamples = len(featureMatrix)
        self.trees = []
        for _ in range(self.numTrees):
            bootstrapIndices = rng.integers(0, numSamples, size=numSamples)
            tree = ManualDecisionTree(maxDepth=self.maxDepth, seed=int(rng.integers(0, 2**31)))
            tree.fit(featureMatrix[bootstrapIndices], [labels[j] for j in bootstrapIndices])
            self.trees.append(tree)

    def predict(self, featureMatrix: np.ndarray):
        votes = np.array([tree.predict(featureMatrix) for tree in self.trees])
        result = [Counter(votes[:, i]).most_common(1)[0][0] for i in range(votes.shape[1])]
        return result


class ManualGradientBoosting:

    def __init__(self, numEstimators: int = 100, learningRate: float = 0.1,
                 maxDepth: int = 3, seed: int = 42):
        self.numEstimators = numEstimators
        self.learningRate = learningRate
        self.maxDepth = maxDepth
        self.seed = seed
        self.classes = None
        self.estimators = []

    def softmax(self, logits: np.ndarray):
        exponents = np.exp(logits - logits.max(axis=1, keepdims=True))
        result = exponents / exponents.sum(axis=1, keepdims=True)
        return result

    def fit(self, featureMatrix: np.ndarray, labels: List[str]):
        self.classes = getUniqueClasses(labels)
        numClasses = len(self.classes)
        numSamples = len(featureMatrix)
        labelInts = labelsToInts(labels, self.classes)
        oneHot = np.zeros((numSamples, numClasses))
        oneHot[np.arange(numSamples), labelInts] = 1.0
        logits = np.zeros((numSamples, numClasses))
        self.estimators = [[] for _ in range(numClasses)]
        rng = np.random.default_rng(self.seed)
        for _ in range(self.numEstimators):
            probs = self.softmax(logits)
            residuals = oneHot - probs
            for classIdx in range(numClasses):
                residualValues = residuals[:, classIdx]
                bins = np.percentile(residualValues, [33, 66])
                residualBins = []
                for v in residualValues:
                    if v <= bins[0]:
                        residualBins.append("lo")
                    elif v <= bins[1]:
                        residualBins.append("md")
                    else:
                        residualBins.append("hi")
                tree = ManualDecisionTree(maxDepth=self.maxDepth, seed=int(rng.integers(0, 2**31)))
                tree.fit(featureMatrix, residualBins)
                predictions = tree.predict(featureMatrix)
                residualArray = np.array(residualBins)
                binMeans = {}
                for b in ("lo", "md", "hi"):
                    if np.any(residualArray == b):
                        binMeans[b] = float(residualValues[residualArray == b].mean())
                    else:
                        binMeans[b] = 0.0
                logits[:, classIdx] += self.learningRate * np.array([binMeans[p] for p in predictions])
                self.estimators[classIdx].append((tree, binMeans))

    def predict(self, featureMatrix: np.ndarray):
        numClasses = len(self.classes)
        logits = np.zeros((len(featureMatrix), numClasses))
        for classIdx in range(numClasses):
            for tree, binMeans in self.estimators[classIdx]:
                logits[:, classIdx] += self.learningRate * np.array([binMeans[p] for p in tree.predict(featureMatrix)])
        result = intsToLabels(logits.argmax(axis=1), self.classes)
        return result


class ManualKNN:

    def __init__(self, numNeighbors: int = 5):
        self.numNeighbors = numNeighbors
        self.trainingFeatures = None
        self.trainingLabels = None

    def fit(self, featureMatrix: np.ndarray, labels: List[str]):
        self.trainingFeatures = featureMatrix.copy()
        self.trainingLabels = labels[:]

    def predict(self, featureMatrix: np.ndarray):
        predictions = []
        for sample in featureMatrix:
            distances = np.sum((self.trainingFeatures - sample) ** 2, axis=1)
            nearestIndices = np.argsort(distances)[:self.numNeighbors]
            predictions.append(Counter(self.trainingLabels[i] for i in nearestIndices).most_common(1)[0][0])
        return predictions


class ManualLogisticRegression:

    def __init__(self, maxIterations: int = 1000, learningRate: float = 0.1, seed: int = 42):
        self.maxIterations = maxIterations
        self.learningRate = learningRate
        self.seed = seed
        self.weights = None
        self.bias = None
        self.classes = None

    def softmax(self, logits: np.ndarray):
        exponents = np.exp(logits - logits.max(axis=1, keepdims=True))
        result = exponents / exponents.sum(axis=1, keepdims=True)
        return result

    def fit(self, featureMatrix: np.ndarray, labels: List[str]):
        self.classes = getUniqueClasses(labels)
        numClasses = len(self.classes)
        numSamples, numFeatures = featureMatrix.shape
        labelInts = labelsToInts(labels, self.classes)
        rng = np.random.default_rng(self.seed)
        self.weights = rng.normal(0, 0.01, (numFeatures, numClasses))
        self.bias = np.zeros(numClasses)
        oneHot = np.zeros((numSamples, numClasses))
        oneHot[np.arange(numSamples), labelInts] = 1.0
        for _ in range(self.maxIterations):
            probs = self.softmax(featureMatrix @ self.weights + self.bias)
            gradient = (probs - oneHot) / numSamples
            self.weights -= self.learningRate * (featureMatrix.T @ gradient)
            self.bias -= self.learningRate * gradient.sum(axis=0)

    def predict(self, featureMatrix: np.ndarray):
        result = intsToLabels((featureMatrix @ self.weights + self.bias).argmax(axis=1), self.classes)
        return result


class CrimeRiskPipeline:

    def __init__(self, city: CityGraph, seed: Optional[int] = 42):
        self.city = city
        self.random = random.Random(seed)
        self.numpySeed = seed if seed is not None else 0
        self.bestClassifierName: str = ""
        self.bestClassifier = None

    def computeIndustrialProximity(self, nodeId: int):
        industrialNodes = self.city.getNodesByType(LocationType.INDUSTRIAL)
        if not industrialNodes:
            return 0.0
        minDistance = min(self.city.manhattan(nodeId, i) for i in industrialNodes)
        result = 1.0 / (1.0 + minDistance)
        return result

    def buildFeatureMatrix(self):
        nodeIds = self.city.allNodeIds()
        rows = []
        for nid in nodeIds:
            node = self.city.getNode(nid)
            rows.append([
                node.populationDensity,
                self.computeIndustrialProximity(nid),
                1.0 if node.locationType == LocationType.RESIDENTIAL else 0.0,
                1.0 if node.locationType == LocationType.INDUSTRIAL else 0.0,
            ])
        return nodeIds, np.array(rows, dtype=float)

    def clusterNodes(self, scaledFeatures: np.ndarray):
        result = runKMeans(scaledFeatures, numClusters=3, numInits=10, maxIterations=300, seed=self.numpySeed)
        return result

    def rankClustersByRisk(self, nodeIds: List[int], rawFeatures: np.ndarray,
                           clusterLabels: np.ndarray):
        scoresByCluster: Dict[int, List[float]] = defaultdict(list)
        for i, nid in enumerate(nodeIds):
            populationDensity = rawFeatures[i, 0]
            industrialProximity = rawFeatures[i, 1]
            scoresByCluster[int(clusterLabels[i])].append(0.55 * populationDensity + 0.45 * industrialProximity)
        avgScorePerCluster = {c: sum(v) / len(v) for c, v in scoresByCluster.items()}
        rankedClusters = sorted(avgScorePerCluster, key=avgScorePerCluster.get)
        numClusters = len(rankedClusters)
        result = {c: rank / max(numClusters - 1, 1) for rank, c in enumerate(rankedClusters)}
        return result

    def getLocationTypeModifier(self, locationType: LocationType):
        if locationType == LocationType.INDUSTRIAL:
            return 0.20
        if locationType in (LocationType.HOSPITAL, LocationType.SCHOOL):
            return -0.15
        if locationType == LocationType.RESIDENTIAL:
            return 0.05
        return 0.0

    def generateSyntheticLabels(self, nodeIds: List[int], rawFeatures: np.ndarray,
                                clusterLabels: np.ndarray, clusterRiskRanks: Dict[int, float]):
        scores: List[float] = []
        for i, nid in enumerate(nodeIds):
            node = self.city.getNode(nid)
            clusterRank = clusterRiskRanks.get(int(clusterLabels[i]), 0.0)
            noise = self.random.uniform(-0.12, 0.12)
            populationDensity = rawFeatures[i, 0]
            industrialProximity = rawFeatures[i, 1]
            if self.random.random() < 0.10:
                if self.random.random() < 0.5:
                    populationDensity = max(0.0, min(1.0, populationDensity + self.random.uniform(-0.25, 0.25)))
                else:
                    industrialProximity = max(0.0, min(1.0, industrialProximity + self.random.uniform(-0.25, 0.25)))
            scores.append(
                0.30 * populationDensity + 0.50 * industrialProximity + 0.20 * clusterRank
                + self.getLocationTypeModifier(node.locationType) + noise
            )
        sortedScores = sorted(scores)
        n = len(sortedScores)
        lowCutoff = sortedScores[int(round(0.33 * (n - 1)))]
        highCutoff = sortedScores[int(round(0.66 * (n - 1)))]
        result = []
        for s in scores:
            if s <= lowCutoff:
                result.append(RiskLevel.LOW.value)
            elif s <= highCutoff:
                result.append(RiskLevel.MEDIUM.value)
            else:
                result.append(RiskLevel.HIGH.value)
        return result

    def buildClassifierCandidates(self):
        result = [
            ("Random Forest", ManualRandomForest(numTrees=100, maxDepth=10, seed=self.numpySeed)),
            ("Gradient Boosting", ManualGradientBoosting(numEstimators=100, seed=self.numpySeed)),
            ("Decision Tree", ManualDecisionTree(seed=self.numpySeed)),
            ("K-Nearest Neighbours", ManualKNN(numNeighbors=5)),
            ("Logistic Regression", ManualLogisticRegression(maxIterations=1000, seed=self.numpySeed)),
        ]
        return result

    def selectBestClassifier(self, featureMatrix: np.ndarray, labels: List[str]):
        trainFeatures, testFeatures, trainLabels, testLabels = stratifiedTrainTestSplit(
            featureMatrix, labels, testFraction=0.25, seed=self.numpySeed
        )
        bestName = ""
        bestClassifier = None
        bestF1 = -1.0
        for name, classifier in self.buildClassifierCandidates():
            classifier.fit(trainFeatures, trainLabels)
            f1 = computeMacroF1(testLabels, classifier.predict(testFeatures))
            if f1 > bestF1:
                bestF1 = f1
                bestName = name
                bestClassifier = classifier
        return bestName, bestClassifier, bestF1

    def allocatePoliceOfficers(self, predictedLabels: List[str]):
        labelCounts = Counter(predictedLabels)
        total = len(predictedLabels)
        allocation: Dict[str, int] = {}
        assignedSoFar = 0
        for level in [RiskLevel.LOW.value, RiskLevel.MEDIUM.value]:
            officers = round(config.numPoliceOfficers * labelCounts.get(level, 0) / total) if total > 0 else 0
            allocation[level] = max(0, officers)
            assignedSoFar += allocation[level]
        allocation[RiskLevel.HIGH.value] = max(0, config.numPoliceOfficers - assignedSoFar)
        return allocation

    def run(self):
        nodeIds, rawFeatures = self.buildFeatureMatrix()
        scaler = ManualStandardScaler()
        scaledFeatures = scaler.fitTransform(rawFeatures)
        clusterLabels = self.clusterNodes(scaledFeatures)
        clusterRiskRanks = self.rankClustersByRisk(nodeIds, rawFeatures, clusterLabels)
        syntheticLabels = self.generateSyntheticLabels(nodeIds, rawFeatures, clusterLabels, clusterRiskRanks)

        minSamplesRequired = 100
        if len(nodeIds) < minSamplesRequired:
            rng = np.random.default_rng(self.numpySeed)
            augmentationFactor = max(1, minSamplesRequired // len(nodeIds))
            augmentedFeatures = np.tile(scaledFeatures, (augmentationFactor, 1))
            augmentedFeatures += rng.normal(0, 0.05, augmentedFeatures.shape)
            augmentedLabels = syntheticLabels * augmentationFactor
            trainingFeatures = augmentedFeatures
            trainingLabels = augmentedLabels
        else:
            trainingFeatures = scaledFeatures
            trainingLabels = syntheticLabels

        bestName, bestClassifier, bestF1 = self.selectBestClassifier(trainingFeatures, trainingLabels)
        bestClassifier.fit(trainingFeatures, trainingLabels)
        self.bestClassifierName = bestName
        self.bestClassifier = bestClassifier

        predictedLabels = [str(lbl) for lbl in bestClassifier.predict(scaledFeatures)]
        for nid, label in zip(nodeIds, predictedLabels):
            self.city.updateRisk(nid, riskValue[RiskLevel(label)], label=label)

        allocation = self.allocatePoliceOfficers(predictedLabels)
        self.city.policeAllocation = allocation
        counts = dict(Counter(predictedLabels))
        return CrimeRiskResult(
            clusterCount=3,
            labelCounts=counts,
            policeAllocation=allocation,
            bestClassifier=bestName,
            bestF1=round(bestF1, 4),
            message=f"Crime risk pipeline complete. Best classifier: {bestName} (macro-F1={bestF1:.4f})",
        )