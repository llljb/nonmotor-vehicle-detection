"""Lazy, serialized YOLOv5 inference; no weights are redistributed."""
import os
from pathlib import Path
from threading import Lock


class Detector:
    def __init__(self):
        self.model = None
        self.lock = Lock()
        self.names = {s.strip() for s in os.getenv('TARGET_CLASSES', 'bicycle').split(',') if s.strip()}
        self.confidence = float(os.getenv('YOLO_CONFIDENCE', '0.4'))
        if not 0 < self.confidence <= 1:
            raise ValueError('YOLO_CONFIDENCE must be in (0, 1]')

    def _load(self):
        if self.model is not None:
            return
        import torch
        repo, weights = os.getenv('YOLOV5_REPO'), os.getenv('YOLO_WEIGHTS')
        kwargs = {'device': os.getenv('YOLO_DEVICE', 'cpu')}
        if weights and not Path(weights).is_file():
            raise FileNotFoundError('YOLO_WEIGHTS is missing')
        if repo and not Path(repo, 'hubconf.py').is_file():
            raise ValueError('YOLOV5_REPO must contain hubconf.py')
        if weights:
            kwargs['path'] = weights
        self.model = torch.hub.load(repo or 'ultralytics/yolov5:v7.0',
                                    'custom' if weights else 'yolov5s',
                                    source='local' if repo else 'github', trust_repo=True, **kwargs)
        self.model.conf = self.confidence
        self.model.eval()
        available = set(self.model.names.values() if isinstance(self.model.names, dict) else self.model.names)
        if not self.names.issubset(available):
            self.model = None
            raise ValueError('TARGET_CLASSES must match the model class names')

    def predict(self, bgr_image):
        import cv2
        with self.lock:
            self._load()
            result = self.model(cv2.cvtColor(bgr_image, cv2.COLOR_BGR2RGB), size=640)
            detections, annotated = [], bgr_image.copy()
            for x1, y1, x2, y2, score, class_id in result.xyxy[0].detach().cpu().tolist():
                name = self.model.names[int(class_id)]
                if name not in self.names:
                    continue
                box = [int(x1), int(y1), int(x2), int(y2)]
                detections.append({'class_name': name, 'confidence': round(float(score), 4), 'box': box})
                cv2.rectangle(annotated, tuple(box[:2]), tuple(box[2:]), (70, 190, 80), 2)
                cv2.putText(annotated, f'{name} {score:.2f}', (box[0], max(18, box[1] - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, .6, (70, 190, 80), 2)
            return annotated, detections
