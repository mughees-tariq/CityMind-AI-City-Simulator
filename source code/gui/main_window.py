from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import (
    QColor, QBrush, QPen, QFont, QPainter,
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QGridLayout, QLabel, QPushButton, QCheckBox, QSlider, QTextEdit,
    QScrollArea, QFrame, QSpinBox, QDoubleSpinBox, QGroupBox, QProgressBar,
    QGraphicsScene, QGraphicsView, QMessageBox,
)

from city.constants import (
    locationColor, locationLetter, LocationType,
)
import config
from simulation.simulator import CityMindSimulator


bgDark = "#1a1a2e"
bgPanel = "#16213e"
bgCard = "#0f3460"
accent = "#e94560"
accent2 = "#53c0f0"
textMain = "#e0e0e0"
textDim = "#888888"
btnBase = "#0f3460"
btnHover = "#1a4a7a"

cellSize = 30



badgeStyle = {
    "locked": "background:#333;color:#666;border-radius:3px;padding:1px 5px;font-size:10px;",
    "running": "background:#e6a817;color:#000;border-radius:3px;padding:1px 5px;font-size:10px;",
    "done": "background:#27ae60;color:#fff;border-radius:3px;padding:1px 5px;font-size:10px;",
    "error": "background:#e94560;color:#fff;border-radius:3px;padding:1px 5px;font-size:10px;",
}


class ChallengeRow(QWidget):
    # Single challenge row with button and status badge.

    def __init__(self, label: str, callback, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)

        self.btn = QPushButton(label)
        self.btn.setFixedHeight(30)
        self.btn.clicked.connect(callback)
        self.btn.setStyleSheet(f"""
            QPushButton {{
                background:{btnBase};color:{textMain};border:1px solid #2a5a9a;
                border-radius:4px;font-size:12px;text-align:left;padding-left:8px;
            }}
            QPushButton:hover {{ background:{btnHover}; }}
            QPushButton:disabled {{ background:#1a1a2e;color:#444;border-color:#333; }}
        """)

        self.badge = QLabel("Locked")
        self.badge.setStyleSheet(badgeStyle["locked"])
        self.badge.setFixedWidth(52)
        self.badge.setAlignment(Qt.AlignCenter)

        lay.addWidget(self.btn, 1)
        lay.addWidget(self.badge)

    def setStatus(self, status: str):
        # Update badge text and styling based on status.
        labels = {"locked": "Locked", "running": "Running", "done": "Done", "error": "Error"}
        self.badge.setText(labels.get(status, status))
        self.badge.setStyleSheet(badgeStyle.get(status, badgeStyle["locked"]))
        self.btn.setEnabled(status != "locked")

    def lock(self):
        # Mark challenge as locked.
        self.setStatus("locked")

    def markDone(self):
        # Mark challenge as successfully completed.
        self.setStatus("done")

    def markRunning(self):
        # Mark challenge as currently executing.
        self.setStatus("running")

    def markError(self):
        # Mark challenge as failed.
        self.setStatus("error")

    def enable(self):
        # Unlock and mark as ready to run.
        self.btn.setEnabled(True)
        self.badge.setText("Ready")
        self.badge.setStyleSheet("background:#1a4a3a;color:#4fc;border-radius:3px;padding:1px 5px;font-size:10px;")


class CityCanvas(QGraphicsView):
    # Interactive grid visualization with cell/road selection and rendering.

    def __init__(self, gui: "CityMindGUI"):
        super().__init__()
        self.gui = gui
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setBackgroundBrush(QBrush(QColor("#0d0d1a")))
        self.setDragMode(QGraphicsView.NoDrag)
        self.selectedNode: Optional[int] = None
        self.shiftHeld = False
        self.zoomFactor = 1.0
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)

    def keyPressEvent(self, event):
        # Handle keyboard input: Shift flag, R=reroute, WASD=move selected node.
        if event.key() == Qt.Key_Shift:
            self.shiftHeld = True
            super().keyPressEvent(event)
        elif event.key() == Qt.Key_R:
            self.gui.forceReroute()
        elif event.key() in (Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D):
            self.moveSelectedNode(event.key())
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        # Release shift flag.
        if event.key() == Qt.Key_Shift:
            self.shiftHeld = False
        super().keyReleaseEvent(event)

    def moveSelectedNode(self, key):
        # Move the selected node highlight one step via WASD and update editor.
        if self.selectedNode is None:
            return
        city = self.gui.sim.city
        row, col = city.rowCol(self.selectedNode)
        if key == Qt.Key_W:
            row -= 1
        elif key == Qt.Key_S:
            row += 1
        elif key == Qt.Key_A:
            col -= 1
        elif key == Qt.Key_D:
            col += 1
        if not city.inBounds(row, col):
            return  # don't move off the edge
        nid = city.nodeId(row, col)
        self.selectedNode = nid
        self.gui.selectedNid = nid
        self.gui.onCellSelected(nid)
        # Keep newly selected cell visible
        cx = col * cellSize + cellSize // 2
        cy = row * cellSize + cellSize // 2
        self.centerOn(cx, cy)
        self.gui.redraw()

    def wheelEvent(self, event):
        # Zoom grid via Ctrl+scroll wheel (0.3x to 5.0x clamp).
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else 0.87
            newZoom = self.zoomFactor * factor
            if 0.3 <= newZoom <= 5.0:
                self.zoomFactor = newZoom
                self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    def mouseMoveEvent(self, event):
        # Update hover label with cell info.
        pos = self.mapToScene(event.pos())
        col = int(pos.x() // cellSize)
        row = int(pos.y() // cellSize)
        city = self.gui.sim.city
        if city.inBounds(row, col):
            nid = city.nodeId(row, col)
            node = city.getNode(nid)
            riskTier = city.riskLabels.get(nid, "--")
            popStr = f"{node.populationDensity:.2f}"
            riskStr = f"{node.riskIndex:.2f} ({riskTier})"
            accStr = "V" if node.accessible else "X BLOCKED"
            self.gui.lblHover.setText(
                f"Node {nid}  ({row},{col})  Type: {node.locationType.name}  "
                f"Pop: {popStr}  Risk: {riskStr}  Accessible: {accStr}"
            )
        else:
            self.gui.lblHover.setText("Hover over a cell for details")
        super().mouseMoveEvent(event)

    def findClickedRoad(self, sceneX: float, sceneY: float):
        # Return (u, v) if click near road midpoint (snap radius ~16px), else None.
        ROAD_CLICK_RADIUS = cellSize * 0.55
        city = self.gui.sim.city
        size = cellSize
        best = None
        bestDist = ROAD_CLICK_RADIUS

        for u, v, _, _ in city.currentEdges():
            ur, uc = city.rowCol(u)
            vr, vc = city.rowCol(v)
            mx = (uc + vc) / 2 * size + size / 2
            my = (ur + vr) / 2 * size + size / 2
            dist = ((sceneX - mx) ** 2 + (sceneY - my) ** 2) ** 0.5
            if dist < bestDist:
                bestDist = dist
                best = (u, v)
        return best

    def mousePressEvent(self, event):
        # Handle grid/road clicks: shift+click adds civilian, road click toggles block, cell click selects.
        pos = self.mapToScene(event.pos())
        sceneX, sceneY = pos.x(), pos.y()
        col = int(sceneX // cellSize)
        row = int(sceneY // cellSize)
        city = self.gui.sim.city

        if self.shiftHeld or (event.modifiers() & Qt.ShiftModifier):
            # Shift+click: add/remove civilian target.
            if city.inBounds(row, col):
                nid = city.nodeId(row, col)
                if nid in city.civilianTargets:
                    city.civilianTargets.remove(nid)
                    if self.gui.sim.router is not None:
                        rs = self.gui.sim.router.state
                        wasCurrent = (nid == rs.currentTarget)
                        if nid in rs.remainingTargets:
                            rs.remainingTargets.remove(nid)
                        if nid in rs.deferredTargets:
                            rs.deferredTargets.remove(nid)
                        if wasCurrent:
                            self.gui.sim.router.planNextLeg()
                            newTarget = rs.currentTarget
                            self.gui.sim.log.add(
                                "MANUAL",
                                f"Civilian target {nid} removed -- was active target; "
                                f"rerouted to next target: {newTarget}",
                            )
                        else:
                            self.gui.sim.log.add("MANUAL", f"Civilian target removed from node {nid}")
                    else:
                        self.gui.sim.log.add("MANUAL", f"Civilian target removed from node {nid}")
                else:
                    city.civilianTargets.append(nid)
                    if self.gui.sim.router is not None:
                        rs = self.gui.sim.router.state
                        if (nid not in rs.remainingTargets
                                and nid not in rs.visitedTargets
                                and nid not in rs.deferredTargets):
                            rs.remainingTargets.append(nid)
                            self.gui.sim.router.planNextLeg()
                            self.gui.sim.log.add(
                                "MANUAL",
                                f"Civilian target added at node {nid} -- added to active mission; "
                                f"next target: {self.gui.sim.router.state.currentTarget}",
                            )
                        else:
                            self.gui.sim.log.add("MANUAL", f"Civilian target added at node {nid}")
                    else:
                        self.gui.sim.log.add("MANUAL", f"Civilian target added at node {nid}")
                self.gui.redraw()
                self.gui.refreshLog()
        else:
            # Check road click first.
            road = self.findClickedRoad(sceneX, sceneY)
            if road is not None and self.gui.cDone[1]:
                u, v = road
                currentlyBlocked = city.isRoadBlocked(u, v)
                if currentlyBlocked:
                    city.unblockRoad(u, v)
                    self.gui.sim.log.add("MANUAL", f"Road {u}<->{v} unblocked")
                    if self.gui.sim.router is not None:
                        ok = self.gui.sim.router.reroute()
                        self.gui.sim.log.add(
                            "C4",
                            f"Road {u}<->{v} unblocked -- reroute: {'shorter path found' if ok else 'no change'}",
                        )
                else:
                    city.blockRoad(u, v)
                    self.gui.sim.log.add("MANUAL", f"Road {u}<->{v} blocked by user")

                    if self.gui.sim.roadBuilder is not None and not self.gui.sim.roadBuilder.hospitalDepotStillBiconnected():
                        self.gui.sim.log.add("CRITICAL", "hospital-depot biconnectivity lost -- fewer than 2 edge-disjoint paths remain")

                    if self.gui.sim.router is not None:
                        if self.gui.sim.router.currentPathHasBlockedRoad():
                            ok = self.gui.sim.router.reroute()
                            self.gui.sim.log.add(...)
                            self.gui.sim.log.add(
                                "C4",
                                f"Road {u}<->{v} blocked -- auto-reroute: {'success' if ok else 'no path'}",
                            )
                self.gui.redraw()
                self.gui.refreshLog()
            elif city.inBounds(row, col):
                # Cell click: select node.
                nid = city.nodeId(row, col)
                self.selectedNode = nid
                self.gui.onCellSelected(nid)
                self.gui.redraw()

        super().mousePressEvent(event)

    def draw(self, sim: CityMindSimulator, overlays: dict):
        # Render grid: cells with colors/hatching, roads, routes, ambulances, civilians, trail.
        self.scene.clear()
        city = sim.city
        size = cellSize

        showRoads = overlays["roads"]
        showAmbulances = overlays["ambulances"]
        showRisk = overlays["risk"]
        showRoute = overlays["route"]
        showBlocked = overlays["blocked"]
        showNodeIds = overlays["node_ids"]
        showPop = overlays["pop_density"]
        showRiskIdx = overlays["risk_index"]

        gui = self.gui
        lastBlocked = getattr(gui, "lastBlockedEdge", None)
        visitedTrail = getattr(gui, "visitedTrail", [])

        rescuedSet = set()
        remainingSet = set()
        if sim.router is not None:
            rescuedSet = set(sim.router.state.visitedTargets)
            remainingSet = set(sim.router.state.remainingTargets)

        # Render cells.
        for nid, node in city.nodes.items():
            x1 = node.col * size
            y1 = node.row * size

            hexCol = locationColor[node.locationType]
            fill = QColor(hexCol)

            if showRisk and node.riskIndex > 0:
                r = 255
                gb = int(245 - 140 * node.riskIndex)
                gb = max(0, gb)
                fill = QColor(r, gb, gb)

            rect = self.scene.addRect(
                x1, y1, size - 1, size - 1,
                QPen(QColor("#2a2a3e"), 0.5),
                QBrush(fill),
            )

            if nid == self.selectedNode:
                sel = self.scene.addRect(
                    x1, y1, size - 1, size - 1,
                    QPen(QColor(accent), 2.5),
                    QBrush(Qt.transparent),
                )

            letter = locationLetter[node.locationType]
            if letter:
                t = self.scene.addText(letter, QFont("Consolas", 8, QFont.Bold))
                t.setDefaultTextColor(QColor("#ffffff"))
                t.setPos(x1 + size // 2 - 5, y1 + size // 2 - 8)

            if showNodeIds:
                t = self.scene.addText(str(nid), QFont("Consolas", 5))
                t.setDefaultTextColor(QColor("#aaaaaa"))
                t.setPos(x1 + 1, y1 + 1)

            if showPop and node.populationDensity > 0:
                t = self.scene.addText(f"{node.populationDensity:.1f}", QFont("Consolas", 5))
                t.setDefaultTextColor(QColor("#53c0f0"))
                t.setPos(x1 + 1, y1 + size - 11)

            if showRiskIdx and node.riskIndex > 0:
                t = self.scene.addText(f"r{node.riskIndex:.1f}", QFont("Consolas", 5))
                t.setDefaultTextColor(QColor("#ff9944"))
                t.setPos(x1 + size - 20, y1 + 1)

            if showRisk and node.riskIndex >= 0.33:
                if node.riskIndex >= 0.66:
                    hatchAlpha = int(80 + 80 * node.riskIndex)
                    pen = QPen(QColor(255, 60, 60, hatchAlpha), 0.8)
                    step = 4
                else:
                    pen = QPen(QColor(255, 160, 60, 60), 0.7)
                    step = 7
                for d in range(0, size * 2, step):
                    xStart = x1 + max(0, d - size)
                    yStart = y1 + min(d, size - 1)
                    xEnd = x1 + min(d, size - 1)
                    yEnd = y1 + max(0, d - size)
                    self.scene.addLine(xStart, yStart, xEnd, yEnd, pen)
                if node.riskIndex >= 0.66:
                    badgeLbl = "H"
                    badgeCol = QColor(230, 50, 50, 200)
                elif node.riskIndex >= 0.33:
                    badgeLbl = "M"
                    badgeCol = QColor(230, 150, 50, 180)
                else:
                    badgeLbl = "L"
                    badgeCol = QColor(50, 200, 100, 150)
                badgeRect = self.scene.addRect(
                    x1 + size - 9, y1 + size - 9, 8, 8,
                    QPen(Qt.transparent), QBrush(badgeCol),
                )
                badgeT = self.scene.addText(badgeLbl, QFont("Consolas", 4, QFont.Bold))
                badgeT.setDefaultTextColor(QColor("#ffffff"))
                badgeT.setPos(x1 + size - 9, y1 + size - 10)

        # Render roads.
        if showRoads:
            for u, v, _, blocked in city.currentEdges():
                if blocked and not showBlocked:
                    continue
                ur, uc = city.rowCol(u)
                vr, vc = city.rowCol(v)
                x1c = uc * size + size // 2
                y1c = ur * size + size // 2
                x2c = vc * size + size // 2
                y2c = vr * size + size // 2
                if blocked:
                    isFlash = lastBlocked is not None and (
                        (lastBlocked[0] == u and lastBlocked[1] == v) or
                        (lastBlocked[0] == v and lastBlocked[1] == u)
                    )
                    pen = QPen(QColor("#ff8800") if isFlash else QColor("#ff4444"),
                               2.5 if isFlash else 1.5, Qt.DashLine)
                    self.scene.addLine(x1c, y1c, x2c, y2c, pen)
                    mx, my = (x1c + x2c) / 2, (y1c + y2c) / 2
                    xp = QPen(QColor("#ff8800") if isFlash else QColor("#ff0000"),
                              2.0 if isFlash else 1.5)
                    self.scene.addLine(mx - 3, my - 3, mx + 3, my + 3, xp)
                    self.scene.addLine(mx + 3, my - 3, mx - 3, my + 3, xp)
                else:
                    redundancy = getattr(city, "redundancyEdges", set())
                    isRedundancy = tuple(sorted((u, v))) in redundancy
                    pen = QPen(QColor("#f0c040") if isRedundancy else QColor("#4a6fa5"),
                               2 if isRedundancy else 1)
                    self.scene.addLine(x1c, y1c, x2c, y2c, pen)

        # Render visited trail.
        if showRoute and len(visitedTrail) >= 2:
            trailPen = QPen(QColor(0, 200, 100, 90), 2, Qt.DotLine)
            for a, b in zip(visitedTrail, visitedTrail[1:]):
                ar, ac = city.rowCol(a)
                br, bc = city.rowCol(b)
                self.scene.addLine(
                    ac * size + size // 2, ar * size + size // 2,
                    bc * size + size // 2, br * size + size // 2,
                    trailPen,
                )

        # Render A* route.
        if showRoute and sim.router is not None:
            path = sim.router.state.currentPath
            for u, v in zip(path, path[1:]):
                ur, uc = city.rowCol(u)
                vr, vc = city.rowCol(v)
                pen = QPen(QColor("#00ff88"), 3)
                self.scene.addLine(
                    uc * size + size // 2, ur * size + size // 2,
                    vc * size + size // 2, vr * size + size // 2,
                    pen,
                )
            tmNode = sim.router.state.currentPosition
            if tmNode is not None:
                hr, hc = city.rowCol(tmNode)
                cx = hc * size + size // 2
                cy = hr * size + size // 2
                self.scene.addEllipse(cx - 7, cy - 7, 14, 14,
                    QPen(QColor("#ffffff"), 1.5), QBrush(QColor("#00cc66")))
                tm = self.scene.addText("TM", QFont("Consolas", 5, QFont.Bold))
                tm.setDefaultTextColor(QColor("#ffffff"))
                tm.setPos(cx - 7, cy - 6)

        # Render ambulance coverage.
        if showAmbulances:

            for pos in city.ambulancePositions:
                r, c = city.rowCol(pos)
                x = c * size + size // 2
                y = r * size + size // 2
                self.scene.addRect(x - 7, y - 7, 14, 14,
                    QPen(QColor("#ffffff"), 1), QBrush(QColor("#1565c0")))
                radii = getattr(city, "ambulanceCoverageRadii", [])
                idx = city.ambulancePositions.index(pos)
                radius = (radii[idx] if idx < len(radii) else 4.5) * size
                self.scene.addEllipse(x - radius, y - radius, radius * 2, radius * 2,
                    QPen(QColor("#53c0f0"), 1, Qt.DashLine), QBrush(Qt.transparent))

        # Render civilian targets.
        for i, target in enumerate(city.civilianTargets, 1):
            r, c = city.rowCol(target)
            x = c * size + size // 2
            y = r * size + size // 2

            if target in rescuedSet:
                self.scene.addRect(x - 7, y - 7, 14, 14,
                    QPen(QColor("#ffffff"), 1), QBrush(QColor("#27ae60")))
                lbl = self.scene.addText("V", QFont("Consolas", 7, QFont.Bold))
                lbl.setDefaultTextColor(QColor("#ffffff"))
                lbl.setPos(x - 5, y - 7)
            else:
                self.scene.addRect(x - 7, y - 7, 14, 14,
                    QPen(QColor("#ffffff"), 1), QBrush(QColor("#e67e22")))
                lbl = self.scene.addText(f"C{i}", QFont("Consolas", 6, QFont.Bold))
                lbl.setDefaultTextColor(QColor("#ffffff"))
                lbl.setPos(x - 6, y - 15)

        total = city.rows * city.cols
        self.scene.setSceneRect(0, 0, city.cols * size, city.rows * size)


class CityMindGUI(QMainWindow):
    # Main application window orchestrating UI layout and challenge execution.

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CityMind -- Urban Intelligence System")
        self.resize(1400, 860)
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background:{bgDark}; color:{textMain}; font-family:Segoe UI; }}
            QGroupBox {{ border:1px solid #2a3a5a; border-radius:6px; margin-top:10px;
                         font-size:11px; font-weight:bold; color:{accent2}; padding:6px; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:8px; }}
            QScrollArea {{ border:none; }}
            QTextEdit {{ background:#0d0d1a; border:1px solid #2a3a5a; border-radius:4px;
                         color:{textMain}; font-family:Consolas; font-size:11px; }}
            QSlider::groove:horizontal {{ height:4px; background:#2a3a5a; border-radius:2px; }}
            QSlider::handle:horizontal {{ width:12px; height:12px; background:{accent2};
                                          border-radius:6px; margin:-4px 0; }}
            QSpinBox {{ background:#0f3460; border:1px solid #2a5a9a; border-radius:4px;
                        color:{textMain}; padding:2px 4px; }}
            QProgressBar {{ background:#0d0d1a; border:1px solid #2a3a5a; border-radius:4px;
                            text-align:center; color:{textMain}; }}
            QProgressBar::chunk {{ background:{accent2}; border-radius:3px; }}
            QCheckBox {{ spacing:5px; }}
            QCheckBox::indicator {{ width:14px; height:14px; border:1px solid #4a6fa5;
                                    border-radius:3px; background:#0d0d1a; }}
            QCheckBox::indicator:checked {{ background:{accent2}; }}
            QLabel {{ color:{textMain}; }}
        """)

        self.sim = CityMindSimulator(config.defaultRows, config.defaultCols)
        self.autoTimer = QTimer(self)
        self.autoTimer.timeout.connect(self.autoStep)
        self.cDone = [False, False, False, False, False]
        self.lastBlockedEdge: Optional[tuple[int, int]] = None
        self.visitedTrail: list[int] = []
        self.suggestPlacedNode: Optional[int] = None  # node placed by last suggest -- never auto-cleared

        self.overlays = {
            "roads": True,
            "route": True,
            "ambulances": True,
            "risk": True,
            "blocked": True,
            "node_ids": False,
            "pop_density": False,
            "risk_index": False,
        }

        self.buildUI()
        self.updateStats()

    def buildUI(self):
        # Construct main window layout: left (canvas) + right (controls).
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        root.addWidget(self.buildLeft(), 3)
        root.addWidget(self.buildRight(), 1)

    def buildLegend(self):
        # Create color/symbol legend strip.
        w = QWidget()
        w.setStyleSheet(f"background:{bgPanel};border-radius:4px;")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(12)
        items = [
            ("#e2e8f0", "Empty"), ("#16a34a", "Residential"),
            ("#2563eb", "Hospital"), ("#ca8a04", "School"),
            ("#ea580c", "Industrial"), ("#9333ea", "Power Plant"),
            ("#e11d48", "Depot"), ("#1d4ed8", "Ambulance"),
            ("#f97316", "Civilian (waiting)"), ("#27ae60", "Civilian (rescued)"),
            ("#22c55e", "A* Route"), ("#00c864", "Trail"), ("#f0c040", "Redundancy edge"),
        ]
        for color, label in items:
            dot = QLabel()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f"background:{color};border-radius:3px;")
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{textDim};font-size:10px;")
            lay.addWidget(dot)
            lay.addWidget(lbl)
        lay.addStretch()
        return w

    def buildLeft(self):
        # Left panel: grid config, overlay toolbar, legend, canvas, hover bar, stats.
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lay.addWidget(self.buildGridConfig())
        lay.addWidget(self.buildOverlayToolbar())
        lay.addWidget(self.buildLegend())
        lay.addWidget(self.buildCanvas(), 1)
        lay.addWidget(self.buildHoverBar())
        lay.addWidget(self.buildStatsBar())
        return w

    def buildGridConfig(self):
        # Grid size spinners and reset/validate buttons.
        grp = QGroupBox("GRID CONFIGURATION")
        lay = QHBoxLayout(grp)

        lay.addWidget(QLabel("Rows"))
        self.spinRows = QSpinBox()
        self.spinRows.setRange(5, 40)
        self.spinRows.setValue(config.defaultRows)
        lay.addWidget(self.spinRows)

        lay.addWidget(QLabel("x"))

        lay.addWidget(QLabel("Cols"))
        self.spinCols = QSpinBox()
        self.spinCols.setRange(5, 40)
        self.spinCols.setValue(config.defaultCols)
        lay.addWidget(self.spinCols)

        self.lblTotal = QLabel(f"Total nodes: {config.defaultRows * config.defaultCols}")
        self.lblTotal.setStyleSheet(f"color:{textDim};")
        lay.addWidget(self.lblTotal)
        lay.addStretch()

        btnReset = self.btn("Reset Grid", self.resetGrid)
        btnAutofill = self.btn("Auto-Fill (C1)", self.autoFill)
        btnValidate = self.btn("Validate Manual Layout", self.validateManualLayout)
        btnValidate.setToolTip(
            "Check your manual node placement meets minimum requirements\n"
            "and unlock the challenge pipeline without running C1."
        )
        lay.addWidget(btnReset)
        lay.addWidget(btnAutofill)
        lay.addWidget(btnValidate)

        self.spinRows.valueChanged.connect(self.onGridSizeChanged)
        self.spinCols.valueChanged.connect(self.onGridSizeChanged)

        # Node search by row / col
        lay.addWidget(QLabel("  |  Go to:"))
        lay.addWidget(QLabel("Row"))
        self.spinSearchRow = QSpinBox()
        self.spinSearchRow.setRange(0, 39)
        self.spinSearchRow.setFixedWidth(52)
        self.spinSearchRow.setToolTip("Row of node to jump to")
        lay.addWidget(self.spinSearchRow)
        lay.addWidget(QLabel("Col"))
        self.spinSearchCol = QSpinBox()
        self.spinSearchCol.setRange(0, 39)
        self.spinSearchCol.setFixedWidth(52)
        self.spinSearchCol.setToolTip("Column of node to jump to")
        lay.addWidget(self.spinSearchCol)
        btnSearch = self.btn("Search", self.searchNode)
        btnSearch.setToolTip("Select node at (Row, Col) and center view on it")
        lay.addWidget(btnSearch)

        self.spinRows.valueChanged.connect(self.onGridSizeChanged)
        self.spinCols.valueChanged.connect(self.onGridSizeChanged)
        return grp

    def buildOverlayToolbar(self):
        # Overlay toggle checkboxes.
        grp = QGroupBox("OVERLAY TOGGLES")
        lay = QHBoxLayout(grp)
        lay.setSpacing(4)

        overlays = [
            ("Road Network", "roads"),
            ("A* Route", "route"),
            ("Ambulance Coverage", "ambulances"),
            ("Crime Heatmap", "risk"),
            ("Blocked Roads", "blocked"),
            ("Node IDs", "node_ids"),
            ("Pop Density", "pop_density"),
            ("Risk Index", "risk_index"),
        ]
        for label, key in overlays:
            cb = QCheckBox(label)
            cb.setChecked(self.overlays[key])
            cb.toggled.connect(lambda v, k=key: self.toggleOverlay(k, v))
            lay.addWidget(cb)
        lay.addStretch()
        return grp

    def buildHoverBar(self):
        # Bottom info bar for cell hover details.
        bar = QWidget()
        bar.setStyleSheet(f"background:{bgPanel};border-radius:3px;")
        bar.setFixedHeight(20)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 0, 8, 0)
        self.lblHover = QLabel("Hover over a cell for details")
        self.lblHover.setStyleSheet(f"color:{textDim};font-size:10px;font-family:Consolas;")
        lay.addWidget(self.lblHover)
        return bar

    def buildCanvas(self):
        # Interactive grid canvas.
        self.canvas = CityCanvas(self)
        self.canvas.setMinimumSize(400, 400)
        return self.canvas

    def buildStatsBar(self):
        # System statistics display.
        bar = QWidget()
        bar.setStyleSheet(f"background:{bgPanel}; border-radius:4px;")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 4, 8, 4)

        self.statLabels = {}
        stats = [
            ("totalNodes", "Total nodes"),
            ("roadsBuilt", "Roads built"),
            ("highRisk", "High-risk nodes"),
            ("ambulances", "Ambulances placed"),
            ("civilians", "Civilian targets"),
            ("blockedRoads", "Blocked roads"),
            ("simTick", "Sim tick"),
            ("officers", "Officers deployed"),
        ]
        for key, label in stats:
            col = QWidget()
            cl = QVBoxLayout(col)
            cl.setContentsMargins(4, 2, 4, 2)
            val = QLabel("0")
            val.setStyleSheet(f"font-size:18px;font-weight:bold;color:{accent2};")
            val.setAlignment(Qt.AlignCenter)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"font-size:10px;color:{textDim};")
            lbl.setAlignment(Qt.AlignCenter)
            cl.addWidget(val)
            cl.addWidget(lbl)
            lay.addWidget(col)
            self.statLabels[key] = val
            if stats.index((key, label)) < len(stats) - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.VLine)
                sep.setStyleSheet("color:#2a3a5a;")
                lay.addWidget(sep)
        return bar

    def buildRight(self):
        # Right panel: scrollable controls.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(320)
        scroll.setMaximumWidth(380)

        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(8)

        lay.addWidget(self.buildNodeEditor())
        lay.addWidget(self.buildBuildingConfig())
        lay.addWidget(self.buildSimParamConfig())
        lay.addWidget(self.buildChallengeControls())
        lay.addWidget(self.buildSimControls())
        lay.addWidget(self.buildEventLog(), 1)
        lay.addStretch()

        scroll.setWidget(inner)
        return scroll

    def buildBuildingConfig(self):
        # CSP building quantity controls -- +/- per type, defaults from config.
        grp = QGroupBox("CSP BUILDING QUANTITIES  (apply to re-run C1)")
        lay = QGridLayout(grp)
        lay.setSpacing(6)

        # (display label, config attr name, config default)
        self.buildingDefs = [
            ("Hospitals",    "numHospitals",    config.numHospitals),
            ("Schools",      "numSchools",      config.numSchools),
            ("Industrial",   "numIndustrial",   config.numIndustrial),
            ("Power Plants", "numPowerPlants",  config.numPowerPlants),
            ("Depots",       "numDepots",       config.numDepots),
            ("Residential",  "numResidential",  config.numResidential),
        ]
        # Store current counts (start at config defaults)
        self.buildingCounts = {attr: default for _, attr, default in self.buildingDefs}
        self.buildingCountLabels: dict[str, QLabel] = {}

        for row, (label, attr, default) in enumerate(self.buildingDefs):
            nameLbl = QLabel(label)
            nameLbl.setStyleSheet(f"color:{textMain};font-size:11px;")

            btnMinus = QPushButton("-")
            btnMinus.setFixedSize(24, 24)
            btnMinus.setStyleSheet(f"background:{btnBase};color:{textMain};border:1px solid #2a5a9a;border-radius:3px;font-size:14px;")
            btnMinus.clicked.connect(lambda _, a=attr: self.adjustBuildingCount(a, -1))

            countLbl = QLabel(str(default))
            countLbl.setFixedWidth(32)
            countLbl.setAlignment(Qt.AlignCenter)
            countLbl.setStyleSheet(f"color:{accent2};font-weight:bold;font-size:12px;")
            self.buildingCountLabels[attr] = countLbl

            btnPlus = QPushButton("+")
            btnPlus.setFixedSize(24, 24)
            btnPlus.setStyleSheet(f"background:{btnBase};color:{textMain};border:1px solid #2a5a9a;border-radius:3px;font-size:14px;")
            btnPlus.clicked.connect(lambda _, a=attr: self.adjustBuildingCount(a, +1))

            lay.addWidget(nameLbl,  row, 0)
            lay.addWidget(btnMinus, row, 1)
            lay.addWidget(countLbl, row, 2)
            lay.addWidget(btnPlus,  row, 3)

        applyBtn = self.btn("Apply & Re-run C1", self.applyBuildingConfig, accent=True)
        applyBtn.setToolTip("Write counts to config and re-run CSP solver")
        lay.addWidget(applyBtn, len(self.buildingDefs), 0, 1, 4)
        return grp

    def adjustBuildingCount(self, attr: str, delta: int):
        # Increment or decrement a building count (min 0, no upper limit).
        current = self.buildingCounts[attr]
        new_val = max(0, current + delta)
        self.buildingCounts[attr] = new_val
        self.buildingCountLabels[attr].setText(str(new_val))

    def buildSimParamConfig(self):
        # Simulation parameter controls for numAmbulances, numPoliceOfficers,
        # riskCostMultiplier, and defaultRandomSeed.
        grp = QGroupBox("SIMULATION PARAMETERS")
        lay = QGridLayout(grp)
        lay.setSpacing(6)

        lbl_style = f"color:{textMain};font-size:11px;"

        # -- Ambulances (1 .. 20 practical cap) --
        ambLbl = QLabel("Ambulances")
        ambLbl.setStyleSheet(lbl_style)
        ambLbl.setToolTip("Number of ambulances placed by C3 (GA)")
        self.spinAmbulances = QSpinBox()
        self.spinAmbulances.setRange(1, 20)
        self.spinAmbulances.setValue(config.numAmbulances)
        self.spinAmbulances.setFixedWidth(60)
        self.spinAmbulances.setToolTip("Min 1 -- must have at least one ambulance")
        lay.addWidget(ambLbl,              0, 0)
        lay.addWidget(self.spinAmbulances, 0, 1, 1, 3)

        # -- Police officers (0 .. 100) --
        polLbl = QLabel("Police officers")
        polLbl.setStyleSheet(lbl_style)
        polLbl.setToolTip("Total officers allocated by C5 risk model")
        self.spinPolice = QSpinBox()
        self.spinPolice.setRange(0, 100)
        self.spinPolice.setValue(config.numPoliceOfficers)
        self.spinPolice.setFixedWidth(60)
        lay.addWidget(polLbl,          1, 0)
        lay.addWidget(self.spinPolice, 1, 1, 1, 3)

        # -- Risk cost multiplier (0.0 .. 5.0, step 0.05) --
        riskLbl = QLabel("Risk cost mult.")
        riskLbl.setStyleSheet(lbl_style)
        riskLbl.setToolTip(
            "Scales how much high-risk zones inflate travel cost. effectiveCost = baseCost * (1 + multiplier * riskIndex). 0 = risk ignored, 5 = extreme penalty"
        )
        self.spinRisk = QDoubleSpinBox()
        self.spinRisk.setRange(0.0, 5.0)
        self.spinRisk.setSingleStep(0.05)
        self.spinRisk.setDecimals(2)
        self.spinRisk.setValue(config.riskCostMultiplier)
        self.spinRisk.setFixedWidth(70)
        lay.addWidget(riskLbl,       2, 0)
        lay.addWidget(self.spinRisk, 2, 1, 1, 3)

        # -- Random seed (0 .. 99999) --
        seedLbl = QLabel("Random seed")
        seedLbl.setStyleSheet(lbl_style)
        seedLbl.setToolTip(
            "Seed for GA (C3) and simulator flood events. Change to get different simulation outcomes."
        )
        self.spinSeed = QSpinBox()
        self.spinSeed.setRange(0, 99999)
        self.spinSeed.setValue(config.defaultRandomSeed)
        self.spinSeed.setFixedWidth(70)
        lay.addWidget(seedLbl,       3, 0)
        lay.addWidget(self.spinSeed, 3, 1, 1, 3)

        applyBtn = self.btn("Apply parameters", self.applySimParamConfig, accent=True)
        applyBtn.setToolTip(
            "Write values to config. Ambulances/seed: re-run C3 to take effect. Risk multiplier: active immediately on next path query. Police: re-run C5 to take effect."
        )
        lay.addWidget(applyBtn, 4, 0, 1, 4)
        return grp

    def applySimParamConfig(self):
        # Validate then write simulation parameters to config module.
        amb  = self.spinAmbulances.value()
        pol  = self.spinPolice.value()
        risk = self.spinRisk.value()
        seed = self.spinSeed.value()

        errors = []

        # Ambulances must not exceed available non-residential/non-empty nodes.
        city = self.sim.city
        nonResidential = [
            nid for nid, node in city.nodes.items()
            if node.locationType.name not in ("RESIDENTIAL", "EMPTY")
        ]
        if nonResidential and amb > len(nonResidential):
            errors.append(
                f"Ambulances ({amb}) exceeds non-residential node count "
                f"({len(nonResidential)}). Reduce or re-run C1 first."
            )

        if errors:
            QMessageBox.warning(self, "Invalid simulation parameters", "\n\n".join(errors))
            return

        # Warn if risk multiplier is very high (routing distortion).
        if risk > 2.0:
            reply = QMessageBox.question(
                self,
                "High risk multiplier",
                f"Risk cost multiplier is {risk:.2f}. Values above 2.0 can make high-risk zones nearly impassable and may cause C4 routing to fail. Continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        config.numAmbulances      = amb
        config.numPoliceOfficers  = pol
        config.riskCostMultiplier = risk
        config.defaultRandomSeed  = seed

        affected = []
        if amb  != getattr(config, "_prev_amb",  amb):  affected.append("C3 (ambulance placement)")
        if pol  != getattr(config, "_prev_pol",  pol):  affected.append("C5 (police allocation)")
        if seed != getattr(config, "_prev_seed", seed): affected.append("C3 + simulator (seed)")
        config._prev_amb  = amb
        config._prev_pol  = pol
        config._prev_seed = seed
        config._prev_risk = risk

        msg = "Parameters saved to config."
        if affected:
            msg += "\n\nRe-run to apply: " + ", ".join(affected)
        if risk != config.riskCostMultiplier:
            msg += "\n\nRisk multiplier active immediately on next path query."
        QMessageBox.information(self, "Parameters updated", msg)

    def buildNodeEditor(self):
        # Node property editor panel.
        grp = QGroupBox("NODE EDITOR -- Click cell to select")
        lay = QVBoxLayout(grp)

        idRow = QHBoxLayout()
        self.lblNodeId = QLabel("Select a cell on the grid")
        self.lblNodeId.setStyleSheet(f"color:{accent2};font-size:11px;")
        idRow.addWidget(self.lblNodeId)
        lay.addLayout(idRow)

        typeGrp = QGroupBox("Node Type")
        tlay = QGridLayout(typeGrp)
        self.typeBtns = {}
        types = [
            (LocationType.EMPTY, "Empty", 0, 0),
            (LocationType.RESIDENTIAL, "Residential", 0, 1),
            (LocationType.HOSPITAL, "Hospital", 1, 0),
            (LocationType.SCHOOL, "School", 1, 1),
            (LocationType.INDUSTRIAL, "Industrial", 2, 0),
            (LocationType.POWER_PLANT, "Power Plant", 2, 1),
            (LocationType.AMBULANCE_DEPOT, "Amb. Depot", 3, 0),
        ]
        for lt, label, r, c in types:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedHeight(26)
            b.setStyleSheet(f"""
                QPushButton {{ background:{btnBase};color:{textMain};border:1px solid #2a5a9a;
                               border-radius:3px;font-size:11px; }}
                QPushButton:checked {{ background:{accent};color:#fff;border-color:{accent}; }}
                QPushButton:hover {{ background:{btnHover}; }}
            """)
            b.clicked.connect(lambda _, t=lt: self.setNodeType(t))
            tlay.addWidget(b, r, c)
            self.typeBtns[lt] = b
        lay.addWidget(typeGrp)

        slGrp = QGroupBox("Node Properties")
        slLay = QGridLayout(slGrp)
        slLay.addWidget(QLabel("Population Density"), 0, 0)
        self.slPop = QSlider(Qt.Horizontal)
        self.slPop.setRange(0, 100)
        self.slPop.setValue(0)
        self.lblPop = QLabel("0.00")
        self.slPop.valueChanged.connect(lambda v: self.lblPop.setText(f"{v/100:.2f}"))
        slLay.addWidget(self.slPop, 0, 1)
        slLay.addWidget(self.lblPop, 0, 2)

        slLay.addWidget(QLabel("Risk Index (override)"), 1, 0)
        self.slRisk = QSlider(Qt.Horizontal)
        self.slRisk.setRange(0, 100)
        self.slRisk.setValue(0)
        self.lblRiskVal = QLabel("0.00")
        self.slRisk.valueChanged.connect(lambda v: self.lblRiskVal.setText(f"{v/100:.2f}"))
        slLay.addWidget(self.slRisk, 1, 1)
        slLay.addWidget(self.lblRiskVal, 1, 2)
        lay.addWidget(slGrp)

        accRow = QHBoxLayout()
        accRow.addWidget(QLabel("Accessibility"))
        self.btnAccessible = QPushButton("Accessible")
        self.btnBlockedAcc = QPushButton("Blocked")
        for b in (self.btnAccessible, self.btnBlockedAcc):
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setStyleSheet(f"""
                QPushButton {{ background:{btnBase};color:{textMain};border:1px solid #2a5a9a;border-radius:3px;font-size:11px; }}
                QPushButton:checked {{ background:{accent2};color:#000; }}
            """)
        self.btnAccessible.setChecked(True)
        self.btnAccessible.clicked.connect(lambda: self.btnBlockedAcc.setChecked(False))
        self.btnBlockedAcc.clicked.connect(lambda: self.btnAccessible.setChecked(False))
        accRow.addWidget(self.btnAccessible)
        accRow.addWidget(self.btnBlockedAcc)
        lay.addLayout(accRow)

        self.lblRoadsInfo = QLabel("North: --  South: --  East: --  West: --")
        self.lblRoadsInfo.setStyleSheet(f"color:{textDim};font-size:10px;")
        lay.addWidget(self.lblRoadsInfo)

        btnRow = QHBoxLayout()
        applyBtn = self.btn("Apply Changes", self.applyNodeChanges, accent=True)
        suggestBtn = self.btn("Suggest Placement...", self.suggestPlacement)
        suggestBtn.setToolTip(
            "Find best empty cell for the selected node type,\n"
            "or suggest a replacement if the grid has no empty space."
        )
        btnRow.addWidget(applyBtn)
        btnRow.addWidget(suggestBtn)
        lay.addLayout(btnRow)

        self.selectedNid: Optional[int] = None
        return grp

    def buildChallengeControls(self):
        # Challenge execution buttons with status badges.
        grp = QGroupBox("CHALLENGE CONTROLS")
        lay = QVBoxLayout(grp)

        self.cRows = [
            ChallengeRow("C1 -- City Layout (CSP + AC-3)", self.runC1),
            ChallengeRow("C2 -- Road Network (Kruskal + Menger)", self.runC2),
            ChallengeRow("C3 -- Ambulance Placement (GA)", self.runC3),
            ChallengeRow("C4 -- Emergency Routing (A*)", self.runC4),
            ChallengeRow("C5 -- Crime Risk (K-Means + ML)", self.runC5),
        ]
        self.cRows[0].enable()
        for row in self.cRows[1:]:
            row.lock()

        for row in self.cRows:
            lay.addWidget(row)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2a3a5a;")
        lay.addWidget(sep)

        self.btnFullSim = self.btn(">  Run Full Simulation (20 ticks)", self.runFull, accent=True)
        self.btnFullSim.setEnabled(False)
        lay.addWidget(self.btnFullSim)
        return grp

    def buildSimControls(self):
        # Simulation control buttons, tick setting, and speed slider.
        grp = QGroupBox("SIMULATION CONTROLS")
        lay = QVBoxLayout(grp)

        tickCfgRow = QHBoxLayout()
        tickCfgRow.addWidget(QLabel("Max Ticks:"))
        self.spinMaxTicks = QSpinBox()
        self.spinMaxTicks.setRange(1, 500)
        self.spinMaxTicks.setValue(config.simulationTicks)
        self.spinMaxTicks.setFixedWidth(60)
        self.spinMaxTicks.setToolTip("Number of simulation ticks (default 20)")
        tickCfgRow.addWidget(self.spinMaxTicks)

        self.chkUnlimitedTicks = QCheckBox("Run until complete")
        self.chkUnlimitedTicks.setToolTip(
            "Ignore tick count -- run simulation until all civilians rescued/dropped"
        )
        self.chkUnlimitedTicks.toggled.connect(self.onUnlimitedToggled)
        tickCfgRow.addWidget(self.chkUnlimitedTicks)
        tickCfgRow.addStretch()
        lay.addLayout(tickCfgRow)

        tickRow = QHBoxLayout()
        tickRow.addWidget(QLabel("Tick"))
        self.lblTick = QLabel("0 / 20")
        self.lblTick.setStyleSheet(f"color:{accent2};font-weight:bold;")
        tickRow.addWidget(self.lblTick)
        tickRow.addStretch()
        lay.addLayout(tickRow)

        self.progress = QProgressBar()
        self.progress.setRange(0, config.simulationTicks)
        self.progress.setValue(0)
        lay.addWidget(self.progress)

        btnRow = QHBoxLayout()
        self.btnSimReset = self.btn(" Reset", self.simReset)
        self.btnSimPrev = self.btn(" Prev", self.simPrev)
        self.btnSimNext = self.btn(" Next", self.simNext)
        self.btnSimAuto = self.btn(" Auto", self.simAutoToggle)
        self.btnSimPrev.setEnabled(False)
        self.btnSimPrev.setToolTip("Step-back not supported in forward simulation")
        for b in (self.btnSimReset, self.btnSimPrev, self.btnSimNext, self.btnSimAuto):
            btnRow.addWidget(b)
        lay.addLayout(btnRow)

        speedRow = QHBoxLayout()
        speedRow.addWidget(QLabel("Speed"))
        self.slSpeed = QSlider(Qt.Horizontal)
        self.slSpeed.setRange(1, 10)
        self.slSpeed.setValue(5)
        speedRow.addWidget(self.slSpeed)
        speedRow.addWidget(QLabel("Fast"))
        lay.addLayout(speedRow)

        hint = QLabel("Block road: click road  |  Add civilian: Shift+click  |  Force reroute: R")
        hint.setStyleSheet(f"color:{textDim};font-size:10px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return grp

    def buildEventLog(self):
        # Event log text display.
        grp = QGroupBox("EVENT LOG")
        lay = QVBoxLayout(grp)
        self.logText = QTextEdit()
        self.logText.setReadOnly(True)
        self.logText.setMinimumHeight(180)
        lay.addWidget(self.logText)
        return grp

    def btn(self, text, callback=None, accent=False):
        # Create styled button with optional callback.
        b = QPushButton(text)
        b.setFixedHeight(30)
        bg = accent if accent else btnBase
        hv = "#c0303f" if accent else btnHover
        b.setStyleSheet(f"""
            QPushButton {{ background:{bg};color:#fff;border:none;border-radius:4px;
                          font-size:12px;padding:0 8px; }}
            QPushButton:hover {{ background:{hv}; }}
            QPushButton:disabled {{ background:#333;color:#666; }}
        """)
        if callback:
            b.clicked.connect(callback)
        return b

    def redraw(self):
        # Update canvas and statistics.
        self.canvas.draw(self.sim, self.overlays)
        self.updateStats()

    def refreshLog(self):
        # Scroll event log to bottom.
        self.logText.setPlainText(self.sim.log.text())
        sb = self.logText.verticalScrollBar()
        sb.setValue(sb.maximum())

    def updateStats(self):
        # Update all statistics labels.
        city = self.sim.city
        total = city.rows * city.cols
        roads = len([e for e in city.currentEdges()])
        blocked = sum(1 for _, _, _, b in city.currentEdges() if b)
        highRisk = sum(1 for n in city.nodes.values() if n.riskIndex >= 0.66)
        officers = sum(city.policeAllocation.values()) if city.policeAllocation else 0

        self.statLabels["totalNodes"].setText(str(total))
        self.statLabels["roadsBuilt"].setText(str(roads))
        self.statLabels["highRisk"].setText(str(highRisk))
        self.statLabels["ambulances"].setText(str(len(city.ambulancePositions)))
        self.statLabels["civilians"].setText(str(len(city.civilianTargets)))
        self.statLabels["blockedRoads"].setText(str(blocked))
        mt = self.sim.maxTicks
        tick_label = f"{self.sim.tick} / {mt}" if mt > 0 else f"{self.sim.tick} / ?"
        self.statLabels["simTick"].setText(tick_label)
        self.statLabels["officers"].setText(str(officers))

        self.lblTick.setText(tick_label)
        if mt > 0:
            self.progress.setRange(0, mt)
        self.progress.setValue(self.sim.tick)
        self.lblTotal.setText(f"Total nodes: {total}")

    def searchNode(self):
        # Select node at (searchRow, searchCol) and center the canvas on it.
        row = self.spinSearchRow.value()
        col = self.spinSearchCol.value()
        city = self.sim.city
        if not city.inBounds(row, col):
            QMessageBox.warning(self, "Search",
                f"({row}, {col}) is outside the current grid ({city.rows}x{city.cols}).")
            return
        nid = city.nodeId(row, col)
        self.canvas.selectedNode = nid
        self.selectedNid = nid
        self.onCellSelected(nid)
        # Center view on the cell
        cx = col * cellSize + cellSize // 2
        cy = row * cellSize + cellSize // 2
        self.canvas.centerOn(cx, cy)
        self.redraw()

    def toggleOverlay(self, key, value):
        # Toggle overlay visibility.
        self.overlays[key] = value
        self.redraw()

    def onGridSizeChanged(self):
        # Update total node count label.
        r = self.spinRows.value()
        c = self.spinCols.value()
        self.lblTotal.setText(f"Total nodes: {r * c}")

    def resetGrid(self):
        # Create new grid and reset all state.
        r = self.spinRows.value()
        c = self.spinCols.value()
        mt = self.getCurrentMaxTicks()
        self.sim = CityMindSimulator(r, c, maxTicks=mt)
        self.cDone = [False] * 5
        self.canvas.selectedNode = None
        self.selectedNid = None
        self.lastBlockedEdge = None
        self.visitedTrail = []
        self.suggestPlacedNode: Optional[int] = None  
        for i, row in enumerate(self.cRows):
            if i == 0:
                row.enable()
            else:
                row.lock()
        self.btnFullSim.setEnabled(False)
        self.autoTimer.stop()
        self.redraw()
        self.refreshLog()

    def getCurrentMaxTicks(self):
        # 0 = unlimited, else spinbox value.
        if self.chkUnlimitedTicks.isChecked():
            return 0
        return self.spinMaxTicks.value()

    def onUnlimitedToggled(self, checked: bool):
        # Disable spinbox when unlimited is checked; update button label.
        self.spinMaxTicks.setEnabled(not checked)
        label = ">  Run Until Complete" if checked else f">  Run Full Simulation ({self.spinMaxTicks.value()} ticks)"
        self.btnFullSim.setText(label)
        # Update progress bar range
        mt = self.getCurrentMaxTicks()
        self.progress.setRange(0, mt if mt > 0 else 100)

    def applyBuildingConfig(self):
        # Write current +/- counts to config module then reset grid and re-run C1.
        for attr, val in self.buildingCounts.items():
            setattr(config, attr, val)
        # Full reset then re-run C1 with new counts
        self.resetGrid()
        self.runC1()

    def autoFill(self):
        # Run C1 CSP solver.
        self.runC1()

    def validateManualLayout(self):
        # Check manually placed grid meets minimum requirements AND all CSP constraints.
        # Constraints checked directly on graph -- no CSP variable name mapping needed.
        city = self.sim.city

        hospitals   = city.getNodesByType(LocationType.HOSPITAL)
        depots      = city.getNodesByType(LocationType.AMBULANCE_DEPOT)
        residents   = city.getNodesByType(LocationType.RESIDENTIAL)
        industrials = city.getNodesByType(LocationType.INDUSTRIAL)
        schools     = city.getNodesByType(LocationType.SCHOOL)
        powers      = city.getNodesByType(LocationType.POWER_PLANT)

        missing = []
        if not hospitals:
            missing.append("at least 1 Hospital (H)")
        if not depots:
            missing.append("at least 1 Ambulance Depot (D)")
        if not residents:
            missing.append("at least 1 Residential node (R)")

        if missing:
            QMessageBox.warning(
                self,
                "Validation Failed",
                "Manual layout is missing required nodes:\n\n"
                + "\n".join(f"  - {m}" for m in missing)
                + "\n\nPlace these nodes on the grid then try again.",
            )
            return

        HOSPITAL_SPREAD   = 6   # same constant as CityLayoutCSP
        POWER_MAX_HOPS    = 2
        RESIDENT_MAX_HOPS = 3
        DEPOT_MAX_HOPS    = max(4, min(8, int(min(city.rows, city.cols) * 0.4)))

        def is_adjacent(a: int, b: int):
            ar, ac = city.rowCol(a)
            br, bc = city.rowCol(b)
            return abs(ar - br) + abs(ac - bc) == 1

        def manhattan(a: int, b: int):
            ar, ac = city.rowCol(a)
            br, bc = city.rowCol(b)
            return abs(ar - br) + abs(ac - bc)

        violation_lines: list[str] = []

        # Rule 1 -- AdjProhibition: Industrial must not be adjacent to School or Hospital
        for i_nid in industrials:
            ir, ic = city.rowCol(i_nid)
            for s_nid in schools:
                if is_adjacent(i_nid, s_nid):
                    sr, sc = city.rowCol(s_nid)
                    violation_lines.append(
                        f"- [AdjProhibition] Industrial ({ir},{ic}) is adjacent to "
                        f"School ({sr},{sc}).\n"
                        f"  -> Remove Industrial at ({ir},{ic}) or School at ({sr},{sc}), "
                        f"then use 'Suggest Placement...' for an advised position."
                    )
            for h_nid in hospitals:
                if is_adjacent(i_nid, h_nid):
                    hr, hc = city.rowCol(h_nid)
                    violation_lines.append(
                        f"- [AdjProhibition] Industrial ({ir},{ic}) is adjacent to "
                        f"Hospital ({hr},{hc}).\n"
                        f"  -> Remove Industrial at ({ir},{ic}) or Hospital at ({hr},{hc}), "
                        f"then use 'Suggest Placement...' for an advised position."
                    )

        # Rule 2 -- HospitalSpread: hospitals must be >= HOSPITAL_SPREAD apart
        for idx, h1 in enumerate(hospitals):
            for h2 in hospitals[idx + 1:]:
                dist = manhattan(h1, h2)
                if dist < HOSPITAL_SPREAD:
                    r1, c1 = city.rowCol(h1)
                    r2, c2 = city.rowCol(h2)
                    violation_lines.append(
                        f"- [HospitalSpread] Hospitals ({r1},{c1}) and ({r2},{c2}) are "
                        f"only {dist} hop(s) apart (need >= {HOSPITAL_SPREAD}).\n"
                        f"  -> Move one hospital further away, then use 'Suggest Placement...' "
                        f"to find an advised position."
                    )

        # Rule 3 -- PowerProximity: each Power Plant must be within POWER_MAX_HOPS of an Industrial
        for p_nid in powers:
            pr, pc = city.rowCol(p_nid)
            nearest_i = min((manhattan(p_nid, i) for i in industrials), default=999)
            if nearest_i > POWER_MAX_HOPS:
                violation_lines.append(
                    f"- [PowerProximity] Power Plant ({pr},{pc}) has no Industrial zone "
                    f"within {POWER_MAX_HOPS} hops (nearest is {nearest_i} hops away).\n"
                    f"  -> Move Power Plant ({pr},{pc}) closer to an Industrial node, "
                    f"or place an Industrial node nearby, then use 'Suggest Placement...'."
                )

        # Rule 4 -- ResidentCoverage: each Residential must be within RESIDENT_MAX_HOPS of a Hospital
        for r_nid in residents:
            rr, rc = city.rowCol(r_nid)
            nearest_h = min((manhattan(r_nid, h) for h in hospitals), default=999)
            if nearest_h > RESIDENT_MAX_HOPS:
                violation_lines.append(
                    f"- [ResidentCoverage] Residential ({rr},{rc}) has no Hospital "
                    f"within {RESIDENT_MAX_HOPS} hops (nearest is {nearest_h} hops away).\n"
                    f"  -> Move a Hospital closer to ({rr},{rc}), or move this Residential "
                    f"node closer to a Hospital, then use 'Suggest Placement...'."
                )

        # Rule 5 -- DepotProximity: each Ambulance Depot must be within DEPOT_MAX_HOPS of a Hospital
        for d_nid in depots:
            dr, dc = city.rowCol(d_nid)
            nearest_h = min((manhattan(d_nid, h) for h in hospitals), default=999)
            if nearest_h > DEPOT_MAX_HOPS:
                violation_lines.append(
                    f"- [DepotProximity] Ambulance Depot ({dr},{dc}) has no Hospital "
                    f"within {DEPOT_MAX_HOPS} hops (nearest is {nearest_h} hops away).\n"
                    f"  -> Move the Depot closer to a Hospital, or use 'Suggest Placement...' "
                    f"to get an advised position."
                )

        if not violation_lines:
            self.cDone[0] = True
            self.cRows[0].markDone()
            self.cRows[1].enable()
            self.cRows[4].enable()

            self.sim.log.add(
                "C1",
                f"Manual layout validated (all CSP constraints pass): "
                f"{len(hospitals)}H {len(depots)}D {len(residents)}R -- C2 unlocked",
            )
            self.redraw()
            self.refreshLog()

            QMessageBox.information(
                self,
                "Layout Validated V",
                f"Manual layout accepted -- all CSP constraints satisfied:\n\n"
                f"  Hospitals:    {len(hospitals)}\n"
                f"  Depots:       {len(depots)}\n"
                f"  Residential:  {len(residents)}\n"
                f"  Industrial:   {len(industrials)}\n"
                f"  Schools:      {len(schools)}\n"
                f"  Power Plants: {len(powers)}\n\n"
                "C2 (Road Network) is now unlocked.\n"
                "Note: C3 (Ambulance GA) requires residential nodes to cover.",
            )
            return

        # Split into hard vs soft for better alerting -- C2 unlocks regardless
        HARD_TAGS = ("AdjProhibition", "ResidentCoverage", "PowerProximity", "HospitalSpread")
        hardViolations = [v for v in violation_lines if any(tag in v for tag in HARD_TAGS)]
        softViolations = [v for v in violation_lines if not any(tag in v for tag in HARD_TAGS)]

        seen_msgs: set[str] = set()
        for line in violation_lines:
            short = line.split("\n")[0]
            if short not in seen_msgs:
                self.sim.log.add("C1", f"Constraint violation: {short}")
                seen_msgs.add(short)

        # Always unlock C2 -- violations are warnings only
        self.cDone[0] = True
        self.cRows[0].markDone()
        self.cRows[1].enable()
        self.cRows[4].enable()

        if hardViolations:
            self.sim.log.add(
                "C1",
                f"Manual layout has {len(hardViolations)} hard constraint violation(s) -- "
                f"C2 unlocked with warnings",
            )
            report = (
                f"Found {len(hardViolations)} hard constraint violation(s).\n"
                f"C2 (Road Network) is unlocked -- you may continue, but fixing these\n"
                f"violations will produce a better city layout.\n\n"
                + "\n\n".join(hardViolations)
                + (("\n\nAdditional soft warnings:\n\n"
                    + "\n\n".join(softViolations)) if softViolations else "")
                + "\n\n-------------------------------------\n"
                "Fix each issue above, then click 'Validate Manual Layout' again.\n"
                "Tip: select the offending node in the Node Editor and click\n"
                "'Suggest Placement...' to get an AI-advised replacement position."
            )
            self.redraw()
            self.refreshLog()
            QMessageBox.warning(self, "Constraint Violations -- C2 Unlocked", report)
        else:
            self.sim.log.add(
                "C1",
                f"Manual layout has {len(softViolations)} soft violation(s) -- C2 unlocked with warnings",
            )
            report = (
                f"Found {len(softViolations)} soft constraint violation(s).\n"
                f"C2 (Road Network) is unlocked -- you may continue, but fixing these issues\n"
                f"will produce a better (cheaper) road network.\n\n"
                + "\n\n".join(softViolations)
                + "\n\n-------------------------------------\n"
                "Fix each issue above, then click 'Validate Manual Layout' again.\n"
                "Tip: select the offending node in the Node Editor and click\n"
                "'Suggest Placement...' to get an AI-advised replacement position."
            )
            self.redraw()
            self.refreshLog()
            QMessageBox.warning(self, "Soft Warnings -- C2 Unlocked", report)


    def onCellSelected(self, nid: int):
        # Update node editor with selected cell data.
        # If user manually clicks a cell different from the last suggest-placed one,
        # reset the guard so that cell can be relocated freely.
        if nid != self.suggestPlacedNode:
            self.suggestPlacedNode = None
        self.selectedNid = nid
        city = self.sim.city
        node = city.getNode(nid)
        r, c = city.rowCol(nid)
        self.lblNodeId.setText(f"Row: {r}  Col: {c}  ID: {nid}")

        for lt, btn in self.typeBtns.items():
            btn.setChecked(lt == node.locationType)

        self.slPop.setValue(int(node.populationDensity * 100))
        self.slRisk.setValue(int(node.riskIndex * 100))


        self.btnAccessible.setChecked(node.accessible)
        self.btnBlockedAcc.setChecked(not node.accessible)

        dirs = {"North": (-1, 0), "South": (1, 0), "East": (0, 1), "West": (0, -1)}
        parts = []
        for dname, (dr, dc) in dirs.items():
            nr, nc = r + dr, c + dc
            if city.inBounds(nr, nc):
                nid2 = city.nodeId(nr, nc)
                if nid2 in city.roads.get(nid, {}):
                    status = "Blocked" if city.isRoadBlocked(nid, nid2) else "Open"
                else:
                    status = "None"
            else:
                status = "--"
            parts.append(f"{dname}: {status}")
        self.lblRoadsInfo.setText("  ".join(parts))

    def setNodeType(self, lt: LocationType):
        # Uncheck all other type buttons and check selected.
        for t, btn in self.typeBtns.items():
            btn.setChecked(t == lt)

    def applyNodeChanges(self):
        # Apply node editor changes to selected cell.
        if self.selectedNid is None:
            return
        nid = self.selectedNid
        city = self.sim.city
        node = city.getNode(nid)

        oldType = node.locationType
        oldAccessible = node.accessible

        newType = oldType
        for lt, btn in self.typeBtns.items():
            if btn.isChecked():
                newType = lt
                break

        newAccessible = self.btnAccessible.isChecked()

        city.setLocationType(nid, newType)
        city.setPopulationDensity(nid, self.slPop.value() / 100)

        # Derive risk tier label from slider value so riskLabels stays consistent
        # with riskIndex after a manual override (prevents hover/tooltip mismatch).
        manualRiskValue = self.slRisk.value() / 100
        if manualRiskValue >= 0.66:
            manualRiskLabel = "High"
        elif manualRiskValue >= 0.33:
            manualRiskLabel = "Medium"
        else:
            manualRiskLabel = "Low"
        city.updateRisk(nid, manualRiskValue, label=manualRiskLabel)

        city.setAccessible(nid, newAccessible)

        typeChanged = newType != oldType
        accessibleChanged = newAccessible != oldAccessible

        if typeChanged:
            self.invalidateFromChallenge(2)

            if self.sim.tick > 0:
                self.autoTimer.stop()
                self.btnSimAuto.setText(">> Auto")
                self.sim.tick = 0
                self.sim.router = None
                self.sim.city.ambulancePositions = []
                self.sim.city.civilianTargets = []
                self.visitedTrail = []
                self.lastBlockedEdge = None
                self.progress.setValue(0)
                self.lblTick.setText("0 / 20")
                self.btnFullSim.setEnabled(False)
                self.sim.log.add(
                    "EDIT",
                    f"Node {nid} type changed ({oldType.name}->{newType.name}) -- "
                    f"simulation reset to tick 0; C2/C3/C4/C5 invalidated -- re-run C2 onward",
                )
            else:
                self.sim.log.add(
                    "EDIT",
                    f"Node {nid} type changed ({oldType.name}->{newType.name}) -- "
                    f"C2/C3/C4/C5 invalidated; re-run C2 onward to update results",
                )

        if accessibleChanged:
            if not newAccessible:
                if newType == LocationType.EMPTY:
                    self.sim.log.add(
                        "EDIT",
                        f"Node {nid} (EMPTY) marked inaccessible -- road block only; "
                        f"C4 will reroute automatically if path affected",
                    )
                    if self.sim.router is not None and self.sim.router.currentPathHasBlockedRoad():
                        ok = self.sim.router.reroute()
                        self.sim.log.add("C4", f"Auto-reroute after road block: {'success' if ok else 'no path'}")

                elif newType == LocationType.HOSPITAL:
                    hospitalsLeft = [
                        n for n in city.getNodesByType(LocationType.HOSPITAL)
                        if city.getNode(n).accessible and n != nid
                    ]
                    self.invalidateFromChallenge(3)
                    self.sim.log.add(
                        "WARN",
                        f"Hospital {nid} marked inaccessible -- {len(hospitalsLeft)} hospital(s) remain; "
                        f"C3/C4 invalidated -- re-run C3 to reposition ambulances",
                    )

                elif newType == LocationType.AMBULANCE_DEPOT:
                    self.invalidateFromChallenge(3)
                    self.sim.log.add(
                        "WARN",
                        f"Ambulance Depot {nid} marked inaccessible -- C3/C4 invalidated; "
                        f"re-run C3 and C4 (depot is routing start point)",
                    )

                elif newType == LocationType.RESIDENTIAL:
                    self.invalidateFromChallenge(3)
                    self.sim.log.add(
                        "EDIT",
                        f"Residential node {nid} marked inaccessible -- C3 invalidated; "
                        f"re-run C3 to update ambulance coverage",
                    )

                else:
                    self.sim.log.add(
                        "EDIT",
                        f"Node {nid} ({newType.name}) marked inaccessible -- no challenge re-run needed",
                    )
            else:
                self.sim.log.add(
                    "EDIT",
                    f"Node {nid} ({newType.name}) marked accessible again -- "
                    f"re-run affected challenges if needed",
                )

        if not typeChanged and not accessibleChanged:
            self.sim.log.add(
                "EDIT",
                f"Node {nid} properties updated -- re-run C5 to refresh risk predictions with new density",
            )


        self.redraw()
        self.refreshLog()

    def invalidateFromChallenge(self, fromC: int):
        # Lock challenges from_c onward (1-indexed to 0-indexed conversion).
        for i in range(fromC - 1, 5):
            if self.cDone[i]:
                self.cDone[i] = False
                self.cRows[i].enable()

    def suggestPlacement(self):
        # Find best CSP-compliant position for selected node type and place it immediately.

        targetType = None
        for lt, btn in self.typeBtns.items():
            if btn.isChecked():
                targetType = lt
                break
        if targetType is None or targetType == LocationType.EMPTY:
            QMessageBox.information(self, "Suggest Placement",
                                    "Select a node type in the Node Editor first.")
            return

        city = self.sim.city

        # CSP constants (mirror CityLayoutCSP exactly)
        HOSPITAL_SPREAD   = 6
        POWER_MAX_HOPS    = 2
        RESIDENT_MAX_HOPS = 3
        DEPOT_MAX_HOPS    = max(4, min(8, int(min(city.rows, city.cols) * 0.4)))
        I_P_SOFT_MIN_DIST = 3

        rows, cols = city.rows, city.cols
        allNodes   = list(city.allNodeIds())

        hospitals    = city.getNodesByType(LocationType.HOSPITAL)
        industrials  = city.getNodesByType(LocationType.INDUSTRIAL)
        schools      = city.getNodesByType(LocationType.SCHOOL)
        residentials = city.getNodesByType(LocationType.RESIDENTIAL)
        powers       = city.getNodesByType(LocationType.POWER_PLANT)

        def is_adj(a, b):
            ar, ac = city.rowCol(a); br, bc = city.rowCol(b)
            return abs(ar - br) + abs(ac - bc) == 1

        def nearest(nid, group):
            return min((city.manhattan(nid, g) for g in group), default=999)

        # Exclude cell currently occupied by the selected node (we're moving it).
        # Never exclude _suggestPlacedNode -- it holds a real placed node, not a relocation source.
        excluded = (
            {self.selectedNid}
            if self.selectedNid is not None and self.selectedNid != self.suggestPlacedNode
            else set()
        )
        occupied = {nid for nid, nd in city.nodes.items()
                    if nd.locationType != LocationType.EMPTY and nid not in excluded}

        emptyNodes = [nid for nid in allNodes if nid not in occupied]

        # If no empties, allow replacing SCHOOL or POWER_PLANT (least critical)
        REPLACEABLE = {LocationType.SCHOOL, LocationType.POWER_PLANT}
        replaceable_pool = [nid for nid, nd in city.nodes.items()
                            if nd.locationType in REPLACEABLE and nid not in excluded]
        candidates = emptyNodes if emptyNodes else replaceable_pool

        if not candidates:
            QMessageBox.warning(self, "Suggest Placement",
                                "No empty or replaceable nodes available.\n"
                                "Increase grid size or remove a non-critical node manually.")
            return

        # Returns (hard_violations, soft_score).
        # Hard constraints: exactly the three spec rules + DepotProximity for depot.
        # Soft score guides tiebreaking when hard == 0; higher is better.
        def evaluate(nid):
            r, c = city.rowCol(nid)
            hard = 0
            soft = 0.0

            if targetType == LocationType.HOSPITAL:
                # Hard: must not be adjacent to industrial (AdjProhibition)
                for i in industrials:
                    if is_adj(nid, i):
                        hard += 1
                # Hard: must be >= HOSPITAL_SPREAD from other hospitals
                for h in hospitals:
                    if city.manhattan(nid, h) < HOSPITAL_SPREAD:
                        hard += 1
                # Soft: prefer interior cells (>=2 from edge)
                if r < 2 or r > rows - 3 or c < 2 or c > cols - 3:
                    soft -= 2.0
                # Soft: prefer position that covers most residentials within RESIDENT_MAX_HOPS
                covered = sum(1 for rn in residentials
                              if city.manhattan(nid, rn) <= RESIDENT_MAX_HOPS)
                soft += covered
                # Soft bonus: prefer spreading from existing hospitals
                spread = min((city.manhattan(nid, h) for h in hospitals), default=HOSPITAL_SPREAD)
                soft += min(spread, HOSPITAL_SPREAD) * 0.1

            elif targetType == LocationType.RESIDENTIAL:
                # Hard: must be within RESIDENT_MAX_HOPS of a hospital (ResidentCoverage)
                if hospitals and nearest(nid, hospitals) > RESIDENT_MAX_HOPS:
                    hard += 1
                # Soft: prefer closer to hospital
                soft = -nearest(nid, hospitals)

            elif targetType == LocationType.INDUSTRIAL:
                # Hard: must not be adjacent to hospital or school (AdjProhibition)
                for h in hospitals:
                    if is_adj(nid, h):
                        hard += 1
                for s in schools:
                    if is_adj(nid, s):
                        hard += 1
                # Soft: prefer outer margin
                margin_r = max(1, int(rows * 0.35))
                margin_c = max(1, int(cols * 0.35))
                is_outer = (r < margin_r or r >= rows - margin_r
                            or c < margin_c or c >= cols - margin_c)
                if is_outer:
                    soft += 2.0
                # Soft: prefer buffer from sensitive zones
                sensitive = hospitals + schools + residentials
                soft += nearest(nid, sensitive) if sensitive else 0

            elif targetType == LocationType.POWER_PLANT:
                # Hard: must be within POWER_MAX_HOPS of an industrial (PowerProximity)
                if industrials and nearest(nid, industrials) > POWER_MAX_HOPS:
                    hard += 1
                # Hard: must not be adjacent to hospital or school (AdjProhibition)
                for h in hospitals:
                    if is_adj(nid, h):
                        hard += 1
                for s in schools:
                    if is_adj(nid, s):
                        hard += 1
                # Soft: minimise distance to nearest industrial
                soft = -nearest(nid, industrials)

            elif targetType == LocationType.SCHOOL:
                # Hard: must not be adjacent to industrial (AdjProhibition)
                for i in industrials:
                    if is_adj(nid, i):
                        hard += 1
                # Soft: prefer proximity to hospitals
                soft = -nearest(nid, hospitals) if hospitals else 0

            elif targetType == LocationType.AMBULANCE_DEPOT:
                # Hard: must be within DEPOT_MAX_HOPS of a hospital (DepotProximity)
                if hospitals and nearest(nid, hospitals) > DEPOT_MAX_HOPS:
                    hard += 1
                # Soft: centralise relative to residentials
                soft = -nearest(nid, residentials) if residentials else 0

            else:
                soft = 0.0

            return hard, soft

        # Pass 1: candidates with zero hard violations, ranked by soft score descending
        compliant = [(nid, s) for nid in candidates
                     for h, s in [evaluate(nid)] if h == 0]
        if compliant:
            best = max(compliant, key=lambda x: x[1])[0]
            hard_v = 0
        else:
            # Pass 2: no fully compliant position exists anywhere in candidates.
            # Pick fewest hard violations; soft breaks ties. Then diagnose the blocker
            # and prompt the user to remove it instead of silently placing a bad node.
            best = min(candidates, key=lambda nid: (evaluate(nid)[0], -evaluate(nid)[1]))
            hard_v, _ = evaluate(best)

            if hard_v > 0:
                # Identify which placed node is the root cause of all violations.
                blocker_nid = None
                blocker_msg = ""

                if targetType == LocationType.RESIDENTIAL:
                    # All positions are too far from every hospital -- need a closer hospital
                    if hospitals:
                        best_h = min(hospitals, key=lambda h: nearest(h, candidates))
                        hr, hc = city.rowCol(best_h)
                        blocker_nid = best_h
                        blocker_msg = (
                            f"Every empty cell is more than {RESIDENT_MAX_HOPS} hops from all hospitals.\n"
                            f"  Blocker: Hospital at ({hr},{hc}) -- closest hospital but still too far from any free cell.\n"
                            f"  Fix: Remove Hospital ({hr},{hc}), then use Suggest Placement to move it closer first."
                        )

                elif targetType == LocationType.POWER_PLANT:
                    if industrials:
                        # Find industrial closest to any candidate; if still > POWER_MAX_HOPS away
                        best_i = min(industrials, key=lambda i: nearest(i, candidates))
                        ir, ic = city.rowCol(best_i)
                        blocker_nid = best_i
                        blocker_msg = (
                            f"Every empty cell is more than {POWER_MAX_HOPS} hops from all Industrial zones.\n"
                            f"  Blocker: Industrial at ({ir},{ic}) -- closest industrial but still out of range.\n"
                            f"  Fix: Remove Industrial ({ir},{ic}), then use Suggest Placement to move it adjacent to where you want the Power Plant."
                        )
                    else:
                        blocker_msg = (
                            f"No Industrial zones exist on the grid.\n"
                            f"  Fix: Place an Industrial node within {POWER_MAX_HOPS} hops of where you want the Power Plant, then try Suggest Placement again."
                        )

                elif targetType in (LocationType.INDUSTRIAL, LocationType.HOSPITAL,
                                    LocationType.POWER_PLANT, LocationType.SCHOOL):
                    # Every cell is adjacent to a sensitive node blocking placement
                    blockers = []
                    for h in hospitals:
                        hr, hc = city.rowCol(h)
                        if any(is_adj(c, h) for c in candidates):
                            blockers.append(f"Hospital ({hr},{hc})")
                    for s in schools:
                        sr, sc = city.rowCol(s)
                        if any(is_adj(c, s) for c in candidates):
                            blockers.append(f"School ({sr},{sc})")
                    for i in industrials:
                        ir, ic = city.rowCol(i)
                        if any(is_adj(c, i) for c in candidates):
                            blockers.append(f"Industrial ({ir},{ic})")
                    blocker_list = ", ".join(blockers[:3]) or "unknown"
                    blocker_msg = (
                        f"Every available cell is adjacent to a node that blocks {targetType.name} placement.\n"
                        f"  Blocking nodes: {blocker_list}\n"
                        f"  Fix: Remove or relocate one of these nodes to open a gap, then use Suggest Placement again."
                    )

                elif targetType == LocationType.AMBULANCE_DEPOT:
                    if hospitals:
                        best_h = min(hospitals, key=lambda h: nearest(h, candidates))
                        hr, hc = city.rowCol(best_h)
                        blocker_nid = best_h
                        blocker_msg = (
                            f"Every empty cell is more than {DEPOT_MAX_HOPS} hops from all hospitals.\n"
                            f"  Blocker: Hospital at ({hr},{hc}) -- closest hospital but still out of range.\n"
                            f"  Fix: Remove Hospital ({hr},{hc}), then use Suggest Placement to move it closer to the depot area first."
                        )
                    else:
                        blocker_msg = (
                            f"No Hospital exists on the grid.\n"
                            f"  Fix: Place a Hospital within {DEPOT_MAX_HOPS} hops of where you want the Depot, then try Suggest Placement again."
                        )

                else:
                    blocker_msg = (
                        "No valid position found for this node type.\n"
                        "  Fix: Free up cells by removing less critical nodes."
                    )

                QMessageBox.warning(
                    self, "No Valid Position Available",
                    f"Cannot find a constraint-satisfying position for {targetType.name}.\n\n"
                    f"{blocker_msg}\n\n"
                    "No node has been placed."
                )
                return

        br, bc = city.rowCol(best)
        cur_type = city.getNode(best).locationType

        replacing_note = ""
        if cur_type != LocationType.EMPTY:
            replacing_note = f"\n  (Replaces existing {cur_type.name} at this cell)"

        msg = (
            f"Best position for {targetType.name}:\n"
            f"  Node {best}  (row={br}, col={bc}){replacing_note}\n\n"
            f"Click OK to place {targetType.name} there now."
        )

        reply = QMessageBox.question(self, "Suggested Placement", msg,
                                     QMessageBox.Ok | QMessageBox.Cancel)
        if reply != QMessageBox.Ok:
            return

        # Only clear the old cell if the user had manually selected a placed node
        # to relocate -- never clear a node that was itself placed by a prior suggest.
        if (self.selectedNid is not None
                and self.selectedNid != best
                and self.selectedNid != self.suggestPlacedNode):
            city.setLocationType(self.selectedNid, LocationType.EMPTY)

        city.setLocationType(best, targetType)

        # Set sensible default population density for the placed type
        import random as _rnd
        if targetType == LocationType.RESIDENTIAL:
            city.setPopulationDensity(best, round(_rnd.uniform(0.45, 1.0), 2))
        elif targetType in (LocationType.INDUSTRIAL, LocationType.SCHOOL, LocationType.HOSPITAL):
            city.setPopulationDensity(best, round(_rnd.uniform(0.20, 0.70), 2))
        else:
            city.setPopulationDensity(best, round(_rnd.uniform(0.05, 0.35), 2))

        # Select the newly placed cell and update editor
        self.suggestPlacedNode = best  # mark so future suggests don't clear this cell
        self.canvas.selectedNode = best
        self.selectedNid = best
        self.onCellSelected(best)

        self.sim.log.add("SUGGEST", f"Placed {targetType.name} at node {best} ({br},{bc})")
        self.redraw()
        self.refreshLog()

    def runC1(self):
        # Execute C1 CSP layout solver.
        self.cRows[0].markRunning()
        QApplication.processEvents()
        ok = self.sim.runChallenge1Layout()
        self.cRows[0].markDone() if ok else self.cRows[0].markError()
        self.cDone[0] = ok
        if ok:
            self.cRows[1].enable()
            self.cRows[4].enable()
        self.redraw()
        self.refreshLog()

    def runC2(self):
        # Execute C2 road network builder.
        if not self.cDone[0]:
            return
        self.cRows[1].markRunning()
        QApplication.processEvents()
        ok = self.sim.runChallenge2Roads()
        self.cRows[1].markDone() if ok else self.cRows[1].markError()
        self.cDone[1] = ok
        if ok:
            self.cRows[2].enable()
        self.redraw()
        self.refreshLog()

    def runC3(self):
        # Execute C3 ambulance GA.
        if not self.cDone[1]:
            return
        self.cRows[2].markRunning()
        QApplication.processEvents()
        ok = self.sim.runChallenge3Ambulances()
        self.cRows[2].markDone() if ok else self.cRows[2].markError()
        self.cDone[2] = ok
        if ok:
            self.cRows[3].enable()
        self.redraw()
        self.refreshLog()

    def runC4(self):
        # Execute C4 emergency routing.
        if not self.cDone[2]:
            return
        self.cRows[3].markRunning()
        QApplication.processEvents()
        ok = self.sim.runChallenge4Routing()
        self.cRows[3].markDone() if ok else self.cRows[3].markError()
        self.cDone[3] = ok
        self.visitedTrail = []
        self.lastBlockedEdge = None
        if ok:
            self.checkAllDone()
        self.redraw()
        self.refreshLog()

    def runC5(self):
        # Execute C5 crime risk pipeline.
        if not self.cDone[1]:
            return
        self.cRows[4].markRunning()
        QApplication.processEvents()
        ok = self.sim.runChallenge5Risk()
        self.cRows[4].markDone() if ok else self.cRows[4].markError()
        self.cDone[4] = ok
        self.redraw()
        self.refreshLog()

    def checkAllDone(self):
        # Unlock Run Full Simulation if C1-C4 complete (C5 optional).
        if all(self.cDone[:4]):
            self.btnFullSim.setEnabled(True)

    def runFull(self):
        # Start auto-play simulation (tick count from spinbox/unlimited checkbox).
        mt = self.getCurrentMaxTicks()
        self.sim.maxTicks = mt

        if not self.cDone[4]:
            self.sim.runChallenge5Risk()
            self.cDone[4] = True
            self.cRows[4].markDone()

        if self.sim.router is None:
            if not self.sim.runInitialPipeline():
                self.refreshLog()
                return

        if not self.autoTimer.isActive():
            interval = max(100, 1100 - self.slSpeed.value() * 100)
            self.autoTimer.start(interval)
            self.btnSimAuto.setText("|| Pause")
        self.redraw()
        self.refreshLog()

    def forceReroute(self):
        # Force emergency router to recompute path.
        if self.sim.router:
            ok = self.sim.router.reroute()
            self.sim.log.add("MANUAL", "Force reroute: " + ("success" if ok else "no path"))
            self.redraw()
            self.refreshLog()

    def simReset(self):
        # Reset grid and all simulation state.
        self.resetGrid()

    def simPrev(self):
        # Step back disabled in forward simulation.
        self.sim.log.add("SIM", "Step-back not supported in forward simulation")
        self.refreshLog()

    def simNext(self):
        # Execute single simulation tick.
        if self.sim.router is None:
            if not self.sim.runInitialPipeline():
                self.refreshLog()
                return
        self.runOneTick()
        self.redraw()
        self.refreshLog()

    def simAutoToggle(self):
        # Toggle auto-play timer.
        if self.autoTimer.isActive():
            self.autoTimer.stop()
            self.btnSimAuto.setText(">> Auto")
        else:
            interval = max(100, 1100 - self.slSpeed.value() * 100)
            self.autoTimer.start(interval)
            self.btnSimAuto.setText("|| Pause")

    def isMissionComplete(self):
        # True if the last log entry signals all civilians rescued/mission done.
        if self.sim.log.entries:
            last_msg = self.sim.log.entries[-1][1].lower()
            if "mission complete" in last_msg or "simulation finished" in last_msg:
                return True
        if self.sim.router is not None:
            s = self.sim.router.state
            if not s.remainingTargets and s.currentTarget is None and not s.deferredTargets:
                return True
        return False

    def autoStep(self):
        # Auto-play timer callback: execute one tick per interval.
        mt = self.sim.maxTicks
        # Stop if bounded tick limit reached
        if mt > 0 and self.sim.tick >= mt:
            self.autoTimer.stop()
            self.btnSimAuto.setText(">> Auto")
            return
        # Stop if mission already complete (works for both bounded and unlimited)
        if self.isMissionComplete():
            self.autoTimer.stop()
            self.btnSimAuto.setText(">> Auto")
            self.sim.log.add("END", f"Simulation stopped -- mission complete at tick {self.sim.tick}")
            self.redraw()
            self.refreshLog()
            return
        if self.sim.router is None:
            if not self.sim.runInitialPipeline():
                self.autoTimer.stop()
                return
        ok = self.sim.runTick()
        if not ok:
            self.autoTimer.stop()
            self.btnSimAuto.setText(">> Auto")
        self.redraw()
        self.refreshLog()

    def runOneTick(self):
        # Execute one tick: snapshot trails, detect blocked edges.
        if self.sim.router is not None:
            posBefore = self.sim.router.state.currentPosition
            if posBefore is not None and (not self.visitedTrail or self.visitedTrail[-1] != posBefore):
                self.visitedTrail.append(posBefore)

        openBefore = {(u, v) for u, v, _, bl in self.sim.city.currentEdges() if not bl}
        self.sim.runTick()
        openAfter = {(u, v) for u, v, _, bl in self.sim.city.currentEdges() if not bl}

        newlyBlocked = openBefore - openAfter
        self.lastBlockedEdge = next(iter(newlyBlocked), None)

        if self.sim.router is not None:
            posAfter = self.sim.router.state.currentPosition
            if posAfter is not None and (not self.visitedTrail or self.visitedTrail[-1] != posAfter):
                self.visitedTrail.append(posAfter)


def main():
    # Application entry point.
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = CityMindGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()