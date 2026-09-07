from django.test import RequestFactory, SimpleTestCase

from core.pagination import DEFAULT_PAGE_SIZE, get_page_size, paginate_queryset


class PaginationHelperTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_default_page_size(self):
        request = self.factory.get('/students/')
        self.assertEqual(get_page_size(request), DEFAULT_PAGE_SIZE)

    def test_page_size_is_clamped(self):
        self.assertEqual(get_page_size(self.factory.get('/?per_page=1')), 10)
        self.assertEqual(get_page_size(self.factory.get('/?per_page=1000')), 100)
        self.assertEqual(get_page_size(self.factory.get('/?per_page=50')), 50)

    def test_invalid_page_returns_last_or_first_valid_page(self):
        request = self.factory.get('/?page=999&per_page=25')
        page = paginate_queryset(range(60), request)
        self.assertEqual(page.number, 3)
        self.assertEqual(page.paginator.count, 60)
