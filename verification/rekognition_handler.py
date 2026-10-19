"""
AWS Rekognition Verification.

Handles Face Liveness checks and compares the selfie to the ID photo.
"""

import boto3
import config

class RekognitionHandler:
    def __init__(self):
        if config.DEMO_MODE:
            self.client = None
            return

        try:
            self.client = boto3.client("rekognition", **config.aws_client_kwargs())
        except Exception:
            self.client = None
        
    def verify_liveness(self, session_id: str) -> dict:
        """
        Get Face Liveness session results.
        """
        if not self.client:
            if config.DEMO_MODE:
                return {
                    "status": "SUCCEEDED",
                    "confidence": 99.2
                }
            return {
                "status": "FAILED",
                "confidence": 0
            }

        try:
            response = self.client.get_face_liveness_session_results(
                SessionId=session_id
            )
            return {
                "status": response.get("Status"),
                "confidence": response.get("Confidence")
            }
        except Exception:
            return {
                "status": "FAILED",
                "confidence": 0
            }
            
    def compare_faces(self, selfie_bytes: bytes, id_card_bytes: bytes) -> dict:
        """
        Compare the live selfie against the ID card photo.
        """
        if not selfie_bytes or not id_card_bytes:
            return {"match": False, "similarity": 0}

        if not self.client:
            if config.DEMO_MODE:
                return {
                    "match": True,
                    "similarity": 98.5
                }
            return {"match": False, "similarity": 0}

        try:
            response = self.client.compare_faces(
                SourceImage={'Bytes': selfie_bytes},
                TargetImage={'Bytes': id_card_bytes},
                SimilarityThreshold=80.0
            )
            matches = response.get('FaceMatches', [])
            if matches:
                return {
                    "match": True,
                    "similarity": matches[0]['Similarity']
                }
            return {"match": False, "similarity": 0}
        except Exception:
            return {"match": False, "similarity": 0}
