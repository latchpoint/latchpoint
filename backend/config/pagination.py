from __future__ import annotations

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class EnvelopePagination(PageNumberPagination):
    """
    Pagination that returns `{ data: [...], meta: {...} }`.

    Meta fields use snake_case (Python convention). The frontend API client
    converts them to camelCase.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200

    def get_paginated_response(self, data):
        page_size = self.get_page_size(self.request) or self.page_size
        return Response(
            {
                "data": data,
                "meta": {
                    "page": self.page.number,
                    "page_size": page_size,
                    "total": self.page.paginator.count,
                    "total_pages": self.page.paginator.num_pages,
                    "has_next": self.page.has_next(),
                    "has_previous": self.page.has_previous(),
                },
            }
        )

