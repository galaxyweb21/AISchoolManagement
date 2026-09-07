# library/urls.py
from django.urls import path
from . import views

app_name = 'library'

urlpatterns = [
    # Dashboard & Catalog
    path('', views.library_dashboard, name='library_dashboard'),
    path('catalog/', views.book_list, name='book_list'),
    path('catalog/create/', views.book_create, name='book_create'),
    path('catalog/<uuid:book_id>/', views.book_detail, name='book_detail'),
    path('catalog/<uuid:book_id>/edit/', views.book_edit, name='book_edit'),
    path('catalog/<uuid:book_id>/delete/', views.book_delete, name='book_delete'),

    # Borrowing & Returns
    path('borrowings/', views.borrowing_list, name='borrowing_list'),
    path('borrowings/create/', views.borrowing_create, name='borrowing_create'),
    path('borrowings/<uuid:borrowing_id>/return/', views.return_book, name='return_book'),
    path('borrowings/<uuid:borrowing_id>/mark-lost/', views.mark_lost, name='mark_lost'),

    # =============================================================
    # BOOK CATEGORY CRUD (NEW)
    # =============================================================
    path('categories/', views.book_category_list, name='book_category_list'),
    path('categories/create/', views.book_category_create, name='book_category_create'),
    path('categories/<uuid:category_id>/edit/', views.book_category_edit, name='book_category_edit'),
    path('categories/<uuid:category_id>/delete/', views.book_category_delete, name='book_category_delete'),
]