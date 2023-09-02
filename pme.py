import requests
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel, QDockWidget, QPushButton, QDockWidget, \
    QGridLayout
from PyQt5.QtCore import Qt, QTimer
from qgis.core import Qgis, QgsProject, QgsRasterLayer, QgsProject, QgsApplication, QgsCoordinateReferenceSystem, \
    QgsCoordinateTransform, QgsPointXY
from qgis.gui import QgsMapCanvas
from qgis.utils import iface
from datetime import datetime

PLANET_API_KEY = ''

layerGridDockWidgetInstance = None


class LayerGridDockWidget(QDockWidget):
    def __init__(self, layers):
        super(LayerGridDockWidget, self).__init__()

        self.setWindowTitle("Layer Grid")
        # Create a scroll area
        self.scrollArea = QScrollArea()
        self.scrollArea.setWidgetResizable(True)

        self.widget = QWidget()
        self.setWidget(self.widget)
        self.layout = QGridLayout()
        self.widget.setLayout(self.layout)

        self.scrollArea.setWidget(self.widget)

        self.setWidget(self.scrollArea)

        # Connect the signal
        iface.mapCanvas().extentsChanged.connect(self.sync_zoom)

        self.updateGrid(layers)

    def updateGrid(self, layers):
        # Clear existing widgets from the layout
        for i in reversed(range(self.layout.count())):
            widget = self.layout.itemAt(i).widget()
            if widget is not None:
                widget.deleteLater()

        self.canvases = []

        # Sort layers by date if possible
        def sort_key(layer):
            try:
                return datetime.strptime(layer.name(), '%m/%Y')
            except ValueError:
                return float('inf')

        sorted_layers = sorted(layers, key=sort_key, reverse=True)

        # Add sorted layers to layout
        row = 0
        col = 0
        for layer in sorted_layers:
            label = QLabel(layer.name())
            canvas = QgsMapCanvas()
            canvas.setCanvasColor(Qt.white)
            canvas.setExtent(layer.extent())
            canvas.setLayers([layer])

            self.canvases.append(canvas)

            self.layout.addWidget(label, row, col)
            self.layout.addWidget(canvas, row + 1, col)

            col += 1
            if col > 2:
                col = 0
                row += 2

    def sync_zoom(self):
        main_canvas = iface.mapCanvas()
        extent = main_canvas.extent()

        for canvas in self.canvases:
            canvas.setExtent(extent)
            canvas.refresh()


class PlanetMosaicExplorerWidget(QWidget):
    def __init__(self):
        super(PlanetMosaicSliderWidget, self).__init__()

        if not PLANET_API_KEY:
            msg = iface.messageBar().createMessage("FETCH_MOSAICS", "Please provide your PLANET_API_KEY.")
            iface.messageBar().pushWidget(msg, level=Qgis.Critical)
            return

        self.layout = QVBoxLayout()
        self.label = QLabel("Month: ...")
        self.label.setStyleSheet("color: green; font-size: 25px;")
        self.label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.label)

        # Create a horizontal layout for the slider and buttons
        self.hbox = QHBoxLayout()

        self.startLabel = QLabel("Start Date:")
        self.endLabel = QLabel("End Date:")

        # Add date filters
        self.hbox.addWidget(self.startLabel)
        self.startDateEdit = QDateEdit()
        self.startDateEdit.setDate(QDate.currentDate())
        self.startDateEdit.setCalendarPopup(True)
        self.startDateEdit.setFixedWidth(100)
        self.startDateEdit.setDisplayFormat("dd/MM/yyyy")
        self.hbox.addWidget(self.startDateEdit)

        self.hbox.addWidget(self.endLabel)
        self.endDateEdit = QDateEdit()
        self.endDateEdit.setDate(QDate.currentDate())
        self.endDateEdit.setCalendarPopup(True)
        self.endDateEdit.setFixedWidth(100)
        self.endDateEdit.setDisplayFormat("dd/MM/yyyy")
        self.hbox.addWidget(self.endDateEdit)

        self.coordInput = QLineEdit(self)
        self.coordInput.setPlaceholderText("Point lat,lon (EPSG:4326)")
        self.hbox.addWidget(self.coordInput)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setTickInterval(1)
        self.slider.setValue(1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.play_timelapse)

        self.filterButton = QPushButton("Filter")
        self.filterButton.setCursor(Qt.PointingHandCursor)
        self.filterButton.setIcon(QgsApplication.getThemeIcon('/mActionFilter.svg'))
        self.filterButton.setToolTip('Apply Date Filter')
        self.hbox.addWidget(self.filterButton)

        self.clearFilterButton = QPushButton("Clear")
        self.clearFilterButton.setIcon(QgsApplication.getThemeIcon("/mIconClearText.svg"))
        self.clearFilterButton.setCursor(Qt.PointingHandCursor)
        self.filterButton.setToolTip('Clear Date Filter')
        self.hbox.addWidget(self.clearFilterButton)

        self.playButton = QPushButton("Play")
        self.playButton.setIcon(QgsApplication.getThemeIcon("/mActionPlay.svg"))
        self.playButton.setCursor(Qt.PointingHandCursor)
        self.hbox.addWidget(self.playButton)

        self.stopButton = QPushButton("Stop")
        self.stopButton.setIcon(QgsApplication.getThemeIcon("/mActionStop.svg"))
        self.stopButton.setCursor(Qt.PointingHandCursor)
        self.hbox.addWidget(self.stopButton)

        self.gridButton = QPushButton("Grid")
        self.gridButton.setIcon(QgsApplication.getThemeIcon("/mActionNewTable.svg"))
        self.gridButton.setCursor(Qt.PointingHandCursor)
        self.hbox.addWidget(self.gridButton)

        self.removeButton = QPushButton("Remove Layers")
        self.removeButton.setIcon(QgsApplication.getThemeIcon("/mActionFileExit.svg"))
        self.removeButton.setCursor(Qt.PointingHandCursor)
        self.hbox.addWidget(self.removeButton)

        # Add the horizontal layout to the vertical layout
        self.layout.addLayout(self.hbox)
        self.layout.addWidget(self.slider)
        # Set the layout for the QWidget
        self.setLayout(self.layout)

        # Connect events
        self.removeButton.clicked.connect(self.remove_layers)
        self.playButton.clicked.connect(self.start_timelapse)
        self.stopButton.clicked.connect(self.stop_timelapse)
        self.slider.valueChanged.connect(self.slider_changed)
        self.filterButton.clicked.connect(self.filter_layers)
        self.clearFilterButton.clicked.connect(self.clear_filter)
        self.gridButton.clicked.connect(self.change_visibility_grid)

        self.setLayout(self.layout)
        self.layer_ids = []
        self.current_layer_id = None
        self.current_layer_name = None
        self.mosaics_data = []
        self.fetch_mosaics()

    def fetch_mosaics(self):
        try:
            response = requests.get(f'https://api.planet.com/basemaps/v1/mosaics?api_key={PLANET_API_KEY}', timeout=60)
            if response.status_code == 200:
                mosaics_data = response.json()['mosaics']
                # Filter and rename mosaics
                self.mosaics_data = []
                for mosaic in mosaics_data:
                    name = mosaic['name']
                    if 'planet_medres_normalized_analytic_' in name:
                        date_str = name.split('planet_medres_normalized_analytic_')[1].split('_mosaic')[0]

                        # Skip the mosaic if it doesn't match the 'YYYY-MM' pattern
                        if not re.match(r"^\d{4}-\d{2}$", date_str):
                            continue

                        date = datetime.strptime(date_str, '%Y-%m')
                        renamed = datetime.strftime(date, '%m/%Y')

                        mosaic['name'] = renamed
                        self.mosaics_data.append(mosaic)

                self.init()

        except Exception as e:
            print(f"Error fetching mosaics: {e}")

    def init(self):
        # Sort mosaics by date in descending order (most recent first)
        self.mosaics_data.sort(key=lambda x: datetime.strptime(x['name'], '%m/%Y'), reverse=True)

        self.slider.setMinimum(1)
        self.slider.setMaximum(len(self.mosaics_data))

        # Initialize layers (assuming they are already added)
        self.layer_ids = []

        for mosaic in self.mosaics_data:
            layer_id = self.add_layer(mosaic)
            if layer_id:
                self.layer_ids.append(layer_id)

        # Initially, make the first layer visible
        self.current_layer_id = self.layer_ids[0]
        self.label.setText(f"Month: {self.mosaics_data[0]['name']}")
        self.label.setStyleSheet("color: green; font-size: 25px;")
        QgsProject.instance().layerTreeRoot().findLayer(
            self.current_layer_id
        ).setItemVisibilityChecked(True)

    def add_layer(self, mosaic):
        tile_url = mosaic['_links']['tiles']
        service_url = tile_url.replace('=', '%3D').replace('&', '%26')

        qgis_tms_uri = 'type=xyz&zmin={0}&zmax={1}&url={2}'.format(
            0, 19, service_url
        )

        layer = QgsRasterLayer(qgis_tms_uri, mosaic['name'], 'wms')

        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
            QgsProject.instance().layerTreeRoot().findLayer(layer).setItemVisibilityChecked(False)
            return layer.id()

        return None

    def zoom_to_point(self):
        coord_text = self.coordInput.text()
        lat, lon = map(float, coord_text.split(','))

        # Convert from EPSG:4326 to EPSG:3857
        source_crs = QgsCoordinateReferenceSystem(4326)
        dest_crs = QgsCoordinateReferenceSystem(3857)
        transform = QgsCoordinateTransform(source_crs, dest_crs, QgsProject.instance())  # Include project instance

        point_4326 = QgsPointXY(lon, lat)
        point_3857 = transform.transform(point_4326)

        # Assuming iface.mapCanvas() returns the map canvas
        canvas = iface.mapCanvas()
        canvas.setCenter(point_3857)
        canvas.zoomScale(20000)  # Zoom level, you can adjust this
        canvas.refresh()

    def filter_layers(self):
        # Fetch selected start and end dates
        start_date = self.startDateEdit.date().toString("MM/yyyy")
        end_date = self.endDateEdit.date().toString("MM/yyyy")

        # Convert to Python datetime.date for easier comparison
        start_date_py = datetime.strptime(start_date, '%m/%Y').date()
        end_date_py = datetime.strptime(end_date, '%m/%Y').date()

        # Filter self.mosaics_data based on date, updating in-place
        temp = self.mosaics_data
        self.mosaics_data = [
            mosaic for mosaic in self.mosaics_data
            if start_date_py <= datetime.strptime(mosaic['name'], '%m/%Y').date() <= end_date_py
        ]

        if len(self.mosaics_data) == 0:
            msg = iface.messageBar().createMessage("FILTER", "No result found for the selected date range.")
            button = QAction("Got it", iface.messageBar())
            button.triggered.connect(lambda: iface.messageBar().popWidget(msg))
            msg.addAction(button)
            iface.messageBar().pushWidget(msg, level=Qgis.Critical)
            self.mosaics_data = temp
            del temp
            return

        # Update the slider's maximum value based on the filtered list
        self.slider.setMaximum(len(self.mosaics_data) - 1)

        # Remove existing layers and re-initialize based on filtered data
        self.remove_layers()
        self.init()

        coord = self.coordInput.text()
        if coord:
            self.zoom_to_point()

        del temp

    def clear_filter(self):
        # Resetting the date filters to their initial state
        self.startDateEdit.setDate(QDate.currentDate())
        self.endDateEdit.setDate(QDate.currentDate())

        self.remove_layers()

        # Fetch the mosaics again
        self.fetch_mosaics()

    def remove_layers(self):
        for layer_id in self.layer_ids:
            QgsProject.instance().removeMapLayer(layer_id)
        self.layer_ids.clear()

    def start_timelapse(self):
        self.timer.start(800)

    def stop_timelapse(self):
        self.timer.stop()

    def play_timelapse(self):
        current_value = self.slider.value()
        if current_value >= self.slider.maximum():
            self.slider.setValue(self.slider.minimum())
        else:
            self.slider.setValue(current_value + 1)

    def slider_changed(self):
        index = self.slider.value() - 1

        # Hide the previous layer
        if self.current_layer_id:
            QgsProject.instance().layerTreeRoot().findLayer(
                self.current_layer_id
            ).setItemVisibilityChecked(False)

        # Show the current layer
        self.current_layer_id = self.layer_ids[index]
        layer = QgsProject.instance().layerTreeRoot().findLayer(self.current_layer_id)
        layer.setItemVisibilityChecked(True)
        self.label.setText(f"Month: {layer.name()}")
        self.label.setStyleSheet("color: green; font-size: 25px;")

    def change_visibility_grid(self):
        global layerGridDockWidgetInstance
        layers = list(QgsProject.instance().mapLayers().values())

        # If the dock widget has not been created yet, create it
        if layerGridDockWidgetInstance is None:
            layerGridDockWidgetInstance = LayerGridDockWidget(layers)
            iface.addDockWidget(Qt.RightDockWidgetArea, layerGridDockWidgetInstance)
        else:
            # If it already exists, simply update its grid content
            layerGridDockWidgetInstance.updateGrid(layers)

        layerGridDockWidgetInstance.show()


# Instantiate the widget
planet_mosaic_explorer_widget = PlanetMosaicExplorerWidget()

# Wrap the widget in a QDockWidget
dock = QDockWidget("Planet Mosaic Explorer (PME)")
dock.setWidget(planet_mosaic_explorer_widget)

# Add the QDockWidget to the QGIS interface at the top
iface.addDockWidget(Qt.TopDockWidgetArea, dock)
