"""Party, election and contestant configuration endpoints (spec section 9, Admin group)."""

from typing import Any, ClassVar
from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.concurrency import if_match_version, with_etag
from apps.core.api.idempotency import idempotent_response
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.authz import AUTHENTICATED
from apps.core.domain.permissions import Perm
from apps.core.pagination import KeysetPagination
from apps.elections import selectors, services
from apps.elections.models import Election

from . import serializers as s

IF_MATCH = OpenApiParameter(
    "If-Match", str, OpenApiParameter.HEADER, required=True, description="ETag from your last read"
)
IDEMPOTENCY_KEY = OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)


def _valid(serializer_class: type, request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


# --- Parties ---------------------------------------------------------------------------------


class PartyListView(APIView):
    """The organization's party master list (FR-6.3.4). Only admins change it."""

    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "POST": Perm.CANDIDATES_MANAGE,
    }

    @extend_schema(responses={200: s.PartySerializer(many=True)})
    def get(self, request: Request) -> Response:
        parties = selectors.parties_for(request.actor)  # type: ignore[attr-defined]
        return Response(s.PartySerializer(parties, many=True).data)

    @extend_schema(
        request=s.PartyCreateSerializer,
        responses={201: s.PartySerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.PartyCreateSerializer, request)
        actor = request.actor  # type: ignore[attr-defined]

        def operation() -> tuple[int, dict]:
            return 201, dict(s.PartySerializer(services.create_party(actor, **data)).data)

        return idempotent_response(request, "parties.create", operation)


class PartyDetailView(APIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "PATCH": Perm.CANDIDATES_MANAGE,
        "DELETE": Perm.CANDIDATES_MANAGE,
    }

    @extend_schema(responses={200: s.PartySerializer})
    def get(self, request: Request, party_id: UUID) -> Response:
        party = selectors.party_for(request.actor, party_id)  # type: ignore[attr-defined]
        return with_etag(Response(s.PartySerializer(party).data), party.row_version)

    @extend_schema(
        request=s.PartyUpdateSerializer, responses={200: s.PartySerializer}, parameters=[IF_MATCH]
    )
    def patch(self, request: Request, party_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        party = selectors.party_for(actor, party_id)
        changes = _valid(s.PartyUpdateSerializer, request)
        updated = services.update_party(
            actor, party, expected_version=if_match_version(request), changes=changes
        )
        return with_etag(Response(s.PartySerializer(updated).data), updated.row_version)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, party_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        services.delete_party(actor, selectors.party_for(actor, party_id))
        return Response(status=204)


class PartyLogoView(APIView):
    """Request a presigned upload for a logo (POST) or remove the logo (DELETE)."""

    required_permission = Perm.CANDIDATES_MANAGE

    @extend_schema(request=s.LogoUploadRequestSerializer, responses={200: s.LogoUploadSerializer})
    def post(self, request: Request, party_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        party = selectors.party_for(actor, party_id)
        data = _valid(s.LogoUploadRequestSerializer, request)
        return Response(services.request_logo_upload(actor, party, **data))

    @extend_schema(responses={200: s.PartySerializer})
    def delete(self, request: Request, party_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        party = services.remove_logo(actor, selectors.party_for(actor, party_id))
        return Response(s.PartySerializer(party).data)


class PartyLogoCompleteView(APIView):
    required_permission = Perm.CANDIDATES_MANAGE

    @extend_schema(request=s.LogoUploadCompleteSerializer, responses={200: s.PartySerializer})
    def post(self, request: Request, party_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        party = selectors.party_for(actor, party_id)
        data = _valid(s.LogoUploadCompleteSerializer, request)
        return Response(s.PartySerializer(services.complete_logo_upload(actor, party, **data)).data)


# --- Elections --------------------------------------------------------------------------------


class ElectionPagination(KeysetPagination):
    ordering = "-election_date"


class ElectionListView(StrictQueryParamsMixin, ListAPIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "POST": Perm.ELECTIONS_CONFIGURE,
    }
    serializer_class = s.ElectionSerializer
    pagination_class = ElectionPagination
    allowed_query_params = frozenset({"status"})

    def get_queryset(self) -> QuerySet[Election]:
        qs = selectors.elections_for(self.actor)
        status = self.request.query_params.get("status")
        return qs.filter(status=status) if status else qs

    @extend_schema(
        request=s.ElectionCreateSerializer,
        responses={201: s.ElectionSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request) -> Response:
        data = _valid(s.ElectionCreateSerializer, request)

        def operation() -> tuple[int, dict]:
            election = services.create_election(self.actor, **data)
            return 201, dict(s.ElectionSerializer(election).data)

        return idempotent_response(request, "elections.create", operation)


class ElectionDetailView(APIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "PATCH": Perm.ELECTIONS_CONFIGURE,
        "DELETE": Perm.ELECTIONS_CONFIGURE,
    }

    @extend_schema(responses={200: s.ElectionSerializer})
    def get(self, request: Request, election_id: UUID) -> Response:
        election = selectors.election_for(request.actor, election_id)  # type: ignore[attr-defined]
        return with_etag(Response(s.ElectionSerializer(election).data), election.row_version)

    @extend_schema(
        request=s.ElectionUpdateSerializer,
        responses={200: s.ElectionSerializer},
        parameters=[IF_MATCH],
    )
    def patch(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = selectors.election_for(actor, election_id)
        changes = _valid(s.ElectionUpdateSerializer, request)
        updated = services.update_election(
            actor, election, expected_version=if_match_version(request), changes=changes
        )
        return with_etag(Response(s.ElectionSerializer(updated).data), updated.row_version)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        services.delete_election(actor, selectors.election_for(actor, election_id))
        return Response(status=204)


class ElectionLockView(APIView):
    """Freeze the parties and contestants (FR-6.3.3). Needs a fresh second factor."""

    required_permission = Perm.ELECTIONS_CONFIGURE

    @extend_schema(request=None, responses={200: s.ElectionSerializer})
    def post(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = selectors.election_for(actor, election_id)
        locked = services.transition(actor, election, "LOCKED")
        return with_etag(Response(s.ElectionSerializer(locked).data), locked.row_version)


class ElectionTransitionView(APIView):
    required_permission = Perm.ELECTIONS_CONFIGURE

    @extend_schema(request=s.TransitionSerializer, responses={200: s.ElectionSerializer})
    def post(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = selectors.election_for(actor, election_id)
        target = _valid(s.TransitionSerializer, request)["to"]
        moved = services.transition(actor, election, target)
        return with_etag(Response(s.ElectionSerializer(moved).data), moved.row_version)


class ElectionPartiesView(APIView):
    """The contesting parties in their fixed order. PUT replaces the whole ordered list."""

    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "PUT": Perm.ELECTIONS_CONFIGURE,
    }

    def _body(self, actor: Any, election: Election) -> list[dict[str, Any]]:
        rows = selectors.election_parties(actor, election)
        return [
            dict(s.ElectionPartySerializer(s.ElectionPartySerializer.row(r)).data) for r in rows
        ]

    @extend_schema(responses={200: s.ElectionPartySerializer(many=True)})
    def get(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        return Response(self._body(actor, selectors.election_for(actor, election_id)))

    @extend_schema(
        request=s.ElectionPartiesUpdateSerializer,
        responses={200: s.ElectionPartySerializer(many=True)},
    )
    def put(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = selectors.election_for(actor, election_id)
        data = _valid(s.ElectionPartiesUpdateSerializer, request)
        services.set_election_parties(actor, election, data["party_ids"])
        return Response(self._body(actor, election))


# --- Contestants -----------------------------------------------------------------------------


class ContestantListView(StrictQueryParamsMixin, APIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "POST": Perm.CANDIDATES_MANAGE,
    }
    allowed_query_params = frozenset({"constituency_id"})

    @extend_schema(
        parameters=[OpenApiParameter("constituency_id", UUID)],
        responses={200: s.ContestantSerializer(many=True)},
    )
    def get(self, request: Request, election_id: UUID) -> Response:
        election = selectors.election_for(self.actor, election_id)
        rows = selectors.contestants_for(
            self.actor, election, constituency_id=self.uuid_param("constituency_id")
        )
        return Response(s.ContestantSerializer(rows, many=True).data)

    @extend_schema(
        request=s.ContestantCreateSerializer,
        responses={201: s.ContestantSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, election_id: UUID) -> Response:
        election = selectors.election_for(self.actor, election_id)
        data = _valid(s.ContestantCreateSerializer, request)

        def operation() -> tuple[int, dict]:
            contestant = services.create_contestant(self.actor, election, **data)
            return 201, dict(s.ContestantSerializer(contestant).data)

        return idempotent_response(request, "contestants.create", operation)


class ContestantDetailView(APIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "PATCH": Perm.CANDIDATES_MANAGE,
        "DELETE": Perm.CANDIDATES_MANAGE,
    }

    @extend_schema(responses={200: s.ContestantSerializer})
    def get(self, request: Request, candidate_id: UUID) -> Response:
        candidate = selectors.candidate_for(request.actor, candidate_id)  # type: ignore[attr-defined]
        return with_etag(Response(s.ContestantSerializer(candidate).data), candidate.row_version)

    @extend_schema(
        request=s.ContestantUpdateSerializer,
        responses={200: s.ContestantSerializer},
        parameters=[IF_MATCH],
    )
    def patch(self, request: Request, candidate_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        candidate = selectors.candidate_for(actor, candidate_id)
        data = _valid(s.ContestantUpdateSerializer, request)
        updated = services.update_contestant(
            actor, candidate, expected_version=if_match_version(request), name=data["name"]
        )
        return with_etag(Response(s.ContestantSerializer(updated).data), updated.row_version)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, candidate_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        services.delete_contestant(actor, selectors.candidate_for(actor, candidate_id))
        return Response(status=204)


# --- Configuration issues --------------------------------------------------------------------


class ConfigIssueResolveView(APIView):
    required_permission = Perm.ELECTIONS_CONFIGURE

    @extend_schema(
        request=s.ConfigIssueResolveSerializer,
        responses={200: s.ConfigIssueSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, issue_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        issue = selectors.issue_for(actor, issue_id)
        data = _valid(s.ConfigIssueResolveSerializer, request)

        def operation() -> tuple[int, dict]:
            resolved = services.resolve_issue(actor, issue, note=data["note"])
            return 200, dict(s.ConfigIssueSerializer(resolved).data)

        return idempotent_response(request, f"config_issues.resolve.{issue_id}", operation)
