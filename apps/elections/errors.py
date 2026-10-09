from rest_framework.exceptions import APIException


class ElectionNotEditable(APIException):
    status_code = 409
    default_detail = "Contests and candidates are locked for this election."
    default_code = "election_locked"


class InvalidTransition(APIException):
    status_code = 409
    default_detail = "The election cannot move to that status from its current one."
    default_code = "invalid_transition"


class ConfigurationIncomplete(APIException):
    status_code = 409
    default_detail = "The election configuration is not complete."
    default_code = "configuration_incomplete"
