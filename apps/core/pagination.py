from rest_framework.pagination import CursorPagination


class KeysetPagination(CursorPagination):
    """Keyset (cursor) pagination only; offsets are not offered (spec section 9)."""

    page_size = 50
    page_size_query_param = "limit"
    max_page_size = 200
    ordering = "-id"  # UUIDv7 ids sort by creation time
