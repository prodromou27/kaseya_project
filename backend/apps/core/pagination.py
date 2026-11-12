from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """Bounded server-side pagination. Clients cannot request unbounded pages."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200
