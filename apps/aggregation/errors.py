from rest_framework.exceptions import APIException


class RollupsDrifted(APIException):
    status_code = 409
    default_detail = "The rollups do not match the head versions. Contact an operator."
    default_code = "rollups_drifted"
