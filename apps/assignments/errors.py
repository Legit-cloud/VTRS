from rest_framework.exceptions import APIException


class ElectionNotAssignable(APIException):
    status_code = 409
    default_detail = "Agents can no longer be deployed for this election."
    default_code = "election_not_assignable"


class AlreadyAssigned(APIException):
    status_code = 409
    default_detail = "This agent is already assigned to that polling unit for this election."
    default_code = "already_assigned"


class PollingUnitFullyAssigned(APIException):
    status_code = 409
    default_detail = "That polling unit already has the maximum number of agents."
    default_code = "polling_unit_fully_assigned"
