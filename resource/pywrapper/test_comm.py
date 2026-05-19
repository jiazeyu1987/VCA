from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QLabel
import sys

from ultrasound_service import UltrasoundService

class YourExistingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("你的医疗工作站主程序")
        self.resize(800, 600)

        self.ultrasound_backend = UltrasoundService()

        self.ultrasound_backend.state_updated.connect(self.on_device_state_changed)
        self.ultrasound_backend.frame_received.connect(self.process_ultrasound_frame)

        self.ultrasound_backend.start_engine()

        layout = QVBoxLayout()
        self.image_label = QLabel("正在等待超声图像输入...")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background-color: black; color: white;")
        self.image_label.setMinimumSize(640, 480)

        btn = QPushButton("测试调用 fetch_provider")
        btn.clicked.connect(self.check_provider_data)

        layout.addWidget(self.image_label, stretch=1)
        layout.addWidget(btn)

        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def process_ultrasound_frame(self, image_matrix):
        try:
            height, width, channels = image_matrix.shape

            if channels == 4:
                image_format = QImage.Format_ARGB32
            elif channels == 3:
                image_format = QImage.Format_RGB888
            else:
                image_format = QImage.Format_Grayscale8

            q_img = QImage(image_matrix.data, width, height, channels * width, image_format).copy()

            pixmap = QPixmap.fromImage(q_img)
            self.image_label.setPixmap(pixmap.scaled(
                self.image_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            ))

        except Exception as e:
            print(f"PyQt 显示转换失败: {e}")

    def on_device_state_changed(self, state):
        pass

    def check_provider_data(self):
        data_dict = self.ultrasound_backend.fetch_provider()
        print(data_dict)

    def closeEvent(self, event):
        self.ultrasound_backend.stop_engine()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = YourExistingApp()
    window.show()
    sys.exit(app.exec_())