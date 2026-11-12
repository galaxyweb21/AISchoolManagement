from django.contrib import admin
from .models import *

# Register your models here.


admin.site.register(User)
admin.site.register(Permission)
admin.site.register(Role)
admin.site.register(RolePermission)
admin.site.register(UserRole)
