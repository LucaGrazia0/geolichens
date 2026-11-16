"""Small API bridge for QGIS 3.22+ and QGIS 4, without patching Qt/QGIS."""

from qgis.PyQt.QtCore import QMetaType
from qgis.core import Qgis


if Qgis.QGIS_VERSION_INT >= 33800:
    class FieldType:
        String = QMetaType.Type.QString
        Int = QMetaType.Type.Int
        LongLong = QMetaType.Type.LongLong
        Double = QMetaType.Type.Double
else:
    # QgsField used QVariant.Type before the QGIS 3.38 QMetaType overload.
    from qgis.PyQt.QtCore import QVariant

    class FieldType:
        String = QVariant.Type.String
        Int = QVariant.Type.Int
        LongLong = QVariant.Type.LongLong
        Double = QVariant.Type.Double


if hasattr(Qgis, 'GeometryType'):
    GeometryType = Qgis.GeometryType
else:
    from qgis.core import QgsWkbTypes

    class GeometryType:
        Point = QgsWkbTypes.PointGeometry
        Line = QgsWkbTypes.LineGeometry
        Polygon = QgsWkbTypes.PolygonGeometry


if hasattr(Qgis, 'LayerType'):
    LayerType = Qgis.LayerType
else:
    from qgis.core import QgsMapLayerType

    class LayerType:
        Vector = QgsMapLayerType.VectorLayer
        Raster = QgsMapLayerType.RasterLayer
        VectorTile = QgsMapLayerType.VectorTileLayer


if hasattr(Qgis, 'RasterIdentifyFormat'):
    RASTER_IDENTIFY_VALUE = Qgis.RasterIdentifyFormat.Value
else:
    from qgis.core import QgsRaster
    RASTER_IDENTIFY_VALUE = QgsRaster.IdentifyFormatValue

if hasattr(Qgis, 'RasterResamplingStage'):
    RASTER_RESAMPLE_FILTER = Qgis.RasterResamplingStage.ResampleFilter
else:
    from qgis.core import QgsRasterPipe
    RASTER_RESAMPLE_FILTER = QgsRasterPipe.ResampleFilter

if hasattr(Qgis, 'ShaderInterpolationMethod'):
    SHADER_LINEAR = Qgis.ShaderInterpolationMethod.Linear
else:
    from qgis.core import QgsColorRampShader
    SHADER_LINEAR = QgsColorRampShader.Interpolated

if hasattr(Qgis, 'VectorProviderCapability'):
    ADD_ATTRIBUTES = Qgis.VectorProviderCapability.AddAttributes
else:
    from qgis.core import QgsVectorDataProvider
    ADD_ATTRIBUTES = QgsVectorDataProvider.AddAttributes
