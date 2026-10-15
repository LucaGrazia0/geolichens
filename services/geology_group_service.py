from qgis.core import QgsField, QgsFeatureRequest
from qgis.PyQt.QtCore import QVariant

from .lithology_classifier_service import LithologyClassifierService


class GeologyGroupService:
    """Crea/aggiorna il campo GRUPPO_LITO sul layer geologico.

    La classificazione avviene in tre gruppi: calcareo, siliceo, misto.
    Se il valore non è classificabile, viene scritto 'altro' o 'unknown'.
    """

    TARGET_FIELD = "GRUPPO_LITO"

    def __init__(self):
        self.classifier = LithologyClassifierService()

    def ensure_group_field(self, layer, source_field=None, target_field=None, max_features=None):
        if layer is None or not hasattr(layer, 'fields') or not callable(layer.fields):
            raise ValueError('Layer geologico non valido')

        target_field = target_field or self.TARGET_FIELD
        source_field = source_field or self._auto_source_field(layer)
        if not source_field:
            raise ValueError('Impossibile individuare il campo litologico sorgente')

        field_names = [f.name() for f in layer.fields()]
        started_edit = False
        if not layer.isEditable():
            if not layer.startEditing():
                raise ValueError("Impossibile avviare l'editing del layer geologico")
            started_edit = True

        if target_field not in field_names:
            ok = layer.addAttribute(QgsField(target_field, QVariant.String, len=20))
            if not ok:
                raise ValueError('Impossibile creare il campo GRUPPO_LITO')
            layer.updateFields()
            field_names = [f.name() for f in layer.fields()]

        src_idx = layer.fields().indexOf(source_field)
        dst_idx = layer.fields().indexOf(target_field)
        if src_idx < 0 or dst_idx < 0:
            raise ValueError('Campo sorgente o destinazione non trovato')

        changed = 0
        request = QgsFeatureRequest()
        count = 0
        for feat in layer.getFeatures(request):
            raw = feat[source_field]
            klass = self.classifier.classify(raw)
            if feat[target_field] != klass:
                layer.changeAttributeValue(feat.id(), dst_idx, klass)
                changed += 1
            count += 1
            if max_features and count >= max_features:
                break

        layer.updateFields()
        if started_edit:
            layer.commitChanges()

        return {
            'source_field': source_field,
            'target_field': target_field,
            'changed_count': changed,
        }

    def _auto_source_field(self, layer):
        hints = [
            'GRUPPO_LITO', 'LITOLOGIA', 'DESCRIZIONE', 'DESCRIZION', 'UNITA',
            'FORMAZIONE', 'DESCR', 'NOME', 'SIGLA'
        ]
        names = [f.name() for f in layer.fields()]
        for h in hints:
            for n in names:
                if n.upper() == h.upper() and n.upper() != 'GRUPPO_LITO':
                    return n
        # fallback: longest text-like field name
        for n in names:
            if any(k in n.lower() for k in ['lito', 'descr', 'unit', 'form', 'nome']):
                return n
        return None
