from rest_framework.exceptions import APIException


class ReconciliationBlocked(APIException):
    status_code = 409
    default_detail = "Every counting result must be reviewed before the election is reconciled."
    default_code = "reconciliation_blocked"


class RollupsDrifted(APIException):
    status_code = 409
    default_detail = "The rollups do not match the head versions. Contact an operator."
    default_code = "rollups_drifted"
