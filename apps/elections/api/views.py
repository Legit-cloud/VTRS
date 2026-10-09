"""Election configuration endpoints (spec section 9, Admin group)."""

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


class ElectionLockView(APIView):
    """Freeze contests and candidates (FR-6.3.3). Needs a fresh second factor."""

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


class ContestListView(APIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "POST": Perm.ELECTIONS_CONFIGURE,
    }

    @extend_schema(responses={200: s.ContestSerializer(many=True)})
    def get(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = selectors.election_for(actor, election_id)
        return Response(
            s.ContestSerializer(selectors.contests_for(actor, election), many=True).data
        )

    @extend_schema(
        request=s.ContestCreateSerializer,
        responses={201: s.ContestSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, election_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        election = selectors.election_for(actor, election_id)
        data = _valid(s.ContestCreateSerializer, request)

        def operation() -> tuple[int, dict]:
            contest = services.create_contest(actor, election, **data)
            return 201, dict(s.ContestSerializer(contest).data)

        return idempotent_response(request, "contests.create", operation)


class ContestDetailView(APIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "PATCH": Perm.ELECTIONS_CONFIGURE,
        "DELETE": Perm.ELECTIONS_CONFIGURE,
    }

    @extend_schema(responses={200: s.ContestSerializer})
    def get(self, request: Request, contest_id: UUID) -> Response:
        contest = selectors.contest_for(request.actor, contest_id)  # type: ignore[attr-defined]
        return with_etag(Response(s.ContestSerializer(contest).data), contest.row_version)

    @extend_schema(
        request=s.ContestUpdateSerializer,
        responses={200: s.ContestSerializer},
        parameters=[IF_MATCH],
    )
    def patch(self, request: Request, contest_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        contest = selectors.contest_for(actor, contest_id)
        changes = _valid(s.ContestUpdateSerializer, request)
        updated = services.update_contest(
            actor, contest, expected_version=if_match_version(request), changes=changes
        )
        return with_etag(Response(s.ContestSerializer(updated).data), updated.row_version)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, contest_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        services.delete_contest(actor, selectors.contest_for(actor, contest_id))
        return Response(status=204)


class CandidateListView(APIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "POST": Perm.CANDIDATES_MANAGE,
    }

    @extend_schema(responses={200: s.CandidateSerializer(many=True)})
    def get(self, request: Request, contest_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        contest = selectors.contest_for(actor, contest_id)
        return Response(
            s.CandidateSerializer(selectors.candidates_for(actor, contest), many=True).data
        )

    @extend_schema(
        request=s.CandidateCreateSerializer,
        responses={201: s.CandidateSerializer},
        parameters=[IDEMPOTENCY_KEY],
    )
    def post(self, request: Request, contest_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        contest = selectors.contest_for(actor, contest_id)
        data = _valid(s.CandidateCreateSerializer, request)

        def operation() -> tuple[int, dict]:
            candidate = services.create_candidate(actor, contest, **data)
            return 201, dict(s.CandidateSerializer(candidate).data)

        return idempotent_response(request, "candidates.create", operation)


class CandidateDetailView(APIView):
    required_permissions: ClassVar[dict[str, str]] = {
        "GET": AUTHENTICATED,
        "PATCH": Perm.CANDIDATES_MANAGE,
        "DELETE": Perm.CANDIDATES_MANAGE,
    }

    @extend_schema(responses={200: s.CandidateSerializer})
    def get(self, request: Request, candidate_id: UUID) -> Response:
        candidate = selectors.candidate_for(request.actor, candidate_id)  # type: ignore[attr-defined]
        return with_etag(Response(s.CandidateSerializer(candidate).data), candidate.row_version)

    @extend_schema(
        request=s.CandidateUpdateSerializer,
        responses={200: s.CandidateSerializer},
        parameters=[IF_MATCH],
    )
    def patch(self, request: Request, candidate_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        candidate = selectors.candidate_for(actor, candidate_id)
        changes = _valid(s.CandidateUpdateSerializer, request)
        updated = services.update_candidate(
            actor, candidate, expected_version=if_match_version(request), changes=changes
        )
        return with_etag(Response(s.CandidateSerializer(updated).data), updated.row_version)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, candidate_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        services.delete_candidate(actor, selectors.candidate_for(actor, candidate_id))
        return Response(status=204)
