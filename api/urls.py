from django.urls import path
from .views import *
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r"subjects", SubjectViewSet, basename="subject")
router.register(r"exams", ExamViewSet, basename="exam")
router.register(r"questions", QuestionViewSet, basename="question")
router.register(r"choices", ChoiceViewSet, basename="choice")
router.register(r"departments", DepartmentViewSet)
router.register(r"users", UsersViewSet)
router.register(r"reports", ReportViewSet, basename="reports")


# router.register(r'question-assignments', QuestionAssignmentViewSet, basename='question-assignment')


urlpatterns = [
    path("login/", CustomLoginView.as_view(), name="custom_login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("create_user/", CreateUserView.as_view(), name="create_user"),
    path(
        "question-assignments/<int:exam_id>/",
        QuestionAssignmentViewSet.as_view({"get": "list"}),
        name="question-assignment",
    ),
    path("student-answers", StudentAnswers.as_view(), name="student-answers"),
    path(
        "exams/<int:pk>/start-session/",
        ExamViewSet.as_view({"post": "start_session"}),
        name="start-exam-session",
    ),
    path(
        "exams/<int:pk>/end-session/",
        ExamViewSet.as_view({"post": "end_session"}),
        name="end-exam-session",
    ),
    path(
        "exams/<int:pk>/active-sessions/",
        ExamViewSet.as_view({"get": "active_sessions"}),
        name="retrieve-active-sessions",
    ),
    # path('reports/generate_excel_report/<int:pk>/', ReportViewSet.as_view({'get': 'generate_excel_report'}), name='download-excel')
]

urlpatterns += router.urls
