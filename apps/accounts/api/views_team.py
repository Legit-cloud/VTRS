"""Team, invitations and the caller's own profile (FR-6.11.x, FR-6.2.x)."""

from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import selectors
from apps.accounts.models import Invitation, Membership
from apps.accounts.services import invitations, team
from apps.core.api.idempotency import idempotent_response
from apps.core.api.views import StrictQueryParamsMixin
from apps.core.authz import AUTHENTICATED
from apps.core.domain.permissions import Perm
from apps.core.pagination import KeysetPagination

from . import serializers as s


class MeView(APIView):
    required_permission = AUTHENTICATED
    allow_without_mfa = True

    @extend_schema(responses={200: s.MeSerializer}, tags=["me"])
    def get(self, request: Request) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        membership = selectors.own_membership(actor)
        user = membership.user
        return Response(
            {
                "user_id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "organization": {
                    "id": str(membership.organization_id),
                    "name": membership.organization.name,
                },
                "role": actor.role,
                "scope": {"type": actor.scope.kind, "ids": sorted(str(i) for i in actor.scope.ids)},
                "permissions": sorted(actor.permissions),
                "mfa_enabled": user.mfa_enabled,
                "mfa_required": actor.requires_mfa,
            }
        )


class MemberPagination(KeysetPagination):
    ordering = "-created_at"


class UserListView(StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.USERS_MANAGE
    serializer_class = s.MemberSerializer
    pagination_class = MemberPagination
    allowed_query_params = frozenset({"role"})

    def get_queryset(self) -> QuerySet[Membership]:
        qs = selectors.members_for(self.actor)
        role = self.request.query_params.get("role")
        return qs.filter(role=role) if role else qs


class UserDetailView(APIView):
    required_permission = Perm.USERS_MANAGE

    @extend_schema(responses={200: s.MemberSerializer}, tags=["team"])
    def get(self, request: Request, user_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        membership = selectors.member_for(actor, user_id)
        body = dict(s.MemberSerializer(membership).data)
        body["devices"] = s.DeviceSerializer(
            selectors.devices_of(actor, membership), many=True
        ).data
        return Response(body)


class UserDeactivateView(APIView):
    required_permission = Perm.USERS_MANAGE

    @extend_schema(request=None, responses={200: s.MemberSerializer}, tags=["team"])
    def post(self, request: Request, user_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        membership = selectors.member_for(actor, user_id)

        def operation() -> tuple[int, dict]:
            team.deactivate_user(actor, membership)
            return 200, dict(s.MemberSerializer(selectors.member_for(actor, user_id)).data)

        return idempotent_response(request, "users.deactivate", operation)


class MembershipUpdateView(APIView):
    required_permission = Perm.USERS_MANAGE

    @extend_schema(
        request=s.MembershipUpdateSerializer, responses={200: s.MemberSerializer}, tags=["team"]
    )
    def put(self, request: Request, user_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        membership = selectors.member_for(actor, user_id)
        serializer = s.MembershipUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> tuple[int, dict]:
            updated = team.update_membership(actor, membership, **serializer.validated_data)
            updated.user = membership.user
            return 200, dict(s.MemberSerializer(updated).data)

        return idempotent_response(request, "users.membership", operation)


class DeviceRevokeView(APIView):
    required_permission = Perm.USERS_MANAGE

    @extend_schema(request=None, responses={200: s.DeviceSerializer}, tags=["team"])
    def post(self, request: Request, user_id: UUID, device_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        membership = selectors.member_for(actor, user_id)

        def operation() -> tuple[int, dict]:
            device = team.revoke_device(actor, membership, device_id)
            if device is None:
                raise NotFound()
            return 200, dict(s.DeviceSerializer(device).data)

        return idempotent_response(request, "devices.revoke", operation)


class InvitationListView(StrictQueryParamsMixin, ListAPIView):
    required_permission = Perm.USERS_MANAGE
    serializer_class = s.InvitationSerializer

    def get_queryset(self) -> QuerySet[Invitation]:
        return selectors.invitations_for(self.actor)

    @extend_schema(
        request=s.InvitationCreateSerializer, responses={201: s.InvitationSerializer}, tags=["team"]
    )
    def post(self, request: Request) -> Response:
        serializer = s.InvitationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        def operation() -> tuple[int, dict]:
            invitation = invitations.create_invitation(self.actor, **serializer.validated_data)
            return 201, dict(s.InvitationSerializer(invitation).data)

        return idempotent_response(request, "invitations.create", operation)


class InvitationRevokeView(APIView):
    required_permission = Perm.USERS_MANAGE

    @extend_schema(request=None, responses={200: s.InvitationSerializer}, tags=["team"])
    def post(self, request: Request, invitation_id: UUID) -> Response:
        actor = request.actor  # type: ignore[attr-defined]
        invitation = selectors.invitation_for(actor, invitation_id)

        def operation() -> tuple[int, dict]:
            return 200, dict(
                s.InvitationSerializer(invitations.revoke_invitation(actor, invitation)).data
            )

        return idempotent_response(request, "invitations.revoke", operation)
