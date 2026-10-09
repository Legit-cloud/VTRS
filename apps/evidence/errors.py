from rest_framework.exceptions import APIException


class EvidenceConflict(APIException):
    status_code = 409
    default_detail = "This evidence id is already registered with different details."
    default_code = "evidence_conflict"


class UploadNotFound(APIException):
    status_code = 409
    default_detail = "No uploaded object was found for this evidence. Upload it, then confirm."
    default_code = "upload_not_found"


class EvidenceQuarantined(APIException):
    status_code = 409
    default_detail = "This evidence failed verification and is quarantined."
    default_code = "evidence_quarantined"


class EvidenceNotReady(APIException):
    status_code = 409
    default_detail = "This evidence has not been uploaded yet."
    default_code = "evidence_not_ready"
