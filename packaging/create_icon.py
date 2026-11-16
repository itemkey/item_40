"""Build the vector app mark as a Windows ICO without external artwork."""
from pathlib import Path
import struct

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
image = QImage(256, 256, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor('#171717'))
painter.drawRect(0, 0, 256, 256)
painter.setPen(QPen(QColor('#dddddd'), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.SquareCap))
painter.drawLine(62, 68, 62, 130)
painter.drawLine(62, 130, 126, 130)
painter.drawLine(112, 68, 112, 190)
painter.drawRect(152, 68, 58, 122)
painter.end()
# ICO supports a PNG payload; Qt's ICO plugin is not required during builds.
from PySide6.QtCore import QBuffer, QByteArray, QIODevice
data = QByteArray()
buffer = QBuffer(data)
buffer.open(QIODevice.OpenModeFlag.WriteOnly)
image.save(buffer, 'PNG')
png = bytes(data)
output = Path(__file__).with_name('app.ico')
output.write_bytes(struct.pack('<HHH', 0, 1, 1) + struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(png), 22) + png)
