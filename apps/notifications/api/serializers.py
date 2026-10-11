from rest_framework import serializers

from apps.core.api.serializers import StrictSerializer


class DeliverySerializer(serializers.Serializer):
    channel = serializers.CharField()
    status = serializers.CharField()
    detail = serializers.CharField()
    sent_at = serializers.DateTimeField(allow_null=True)
    delivered_at = serializers.DateTimeField(allow_null=True)


class NotificationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    severity = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    link = serializers.DictField()
    read_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()
    deliveries = DeliverySerializer(many=True)


class UnreadCountSerializer(serializers.Serializer):
    unread = serializers.IntegerField()


class PushTokenSerializer(StrictSerializer):
    token = serializers.CharField(min_length=8, max_length=4096)


class MarkedSerializer(serializers.Serializer):
    marked = serializers.IntegerField()
