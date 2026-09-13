from django.db import migrations, models
import django.core.validators
from decimal import Decimal
import django.db.models.deletion
import uuid

class Migration(migrations.Migration):
    dependencies=[('staff','0005_staff_signature_and_headteacher')]
    operations=[migrations.CreateModel(name='GradeAllowance',fields=[('id',models.UUIDField(default=uuid.uuid4,editable=False,primary_key=True,serialize=False)),('amount',models.DecimalField(blank=True,decimal_places=2,help_text='Custom amount for this grade (leave blank to use the default allowance amount)',max_digits=10,null=True,validators=[django.core.validators.MinValueValidator(Decimal('0.00'))])),('is_percentage',models.BooleanField(default=False,help_text='If True, amount is a percentage of basic salary')),('is_active',models.BooleanField(default=True)),('created_at',models.DateTimeField(auto_now_add=True)),('updated_at',models.DateTimeField(auto_now=True)),('allowance',models.ForeignKey(help_text='The allowance to assign to this grade',on_delete=django.db.models.deletion.CASCADE,related_name='grade_allowances',to='staff.allowance')),('school',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='grade_allowances',to='school.school')),('staff_grade',models.ForeignKey(help_text='The staff grade that receives this allowance',on_delete=django.db.models.deletion.CASCADE,related_name='grade_allowances',to='staff.staffgrade'))],options={'ordering':['staff_grade__level','allowance__name'],'indexes':[models.Index(fields=['staff_grade','allowance'],name='staff_grade_allowance_idx'),models.Index(fields=['staff_grade','is_active'],name='staff_grade_active_idx')]})]
