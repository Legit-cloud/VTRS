from rest_framework.exceptions import APIException


class ElectionNotEditable(APIException):
    status_code = 409
    default_detail = "Parties and contestants are locked for this election."
    default_code = "election_locked"


class InvalidTransition(APIException):
    status_code = 409
    default_detail = "The election cannot move to that status from its current one."
    default_code = "invalid_transition"


class ConfigurationIncomplete(APIException):
    status_code = 409
    default_detail = "The election configuration is not complete."
    default_code = "configuration_incomplete"


class ElectionNotDeletable(APIException):
    status_code = 409
    default_detail = (
        "Only an election that is still being set up can be deleted. "
        "Once it is locked it is part of the record."
    )
    default_code = "election_not_deletable"


class PartyInUse(APIException):
    status_code = 409
    default_detail = "This party is contesting an election. Take it off the election first."
    default_code = "party_in_use"


class PartyLocked(APIException):
    status_code = 409
    default_detail = (
        "A locked election uses this party, so its name and abbreviation can no longer change."
    )
    default_code = "party_locked"


class LogoRejected(APIException):
    status_code = 400
    default_detail = "Use a PNG, JPEG or WebP image of at most 256 KB."
    default_code = "logo_rejected"


class IssueAlreadyResolved(APIException):
    status_code = 409
    default_detail = "This issue is already resolved."
    default_code = "issue_resolved"
