from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.authtoken.models import Token
from django.contrib.auth import get_user_model
from datetime import datetime
from .models import *
from .serializers import *
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from .permissions import IsAdminUser, IsStudentUser
from rest_framework.views import APIView
from django.db.models import Subquery
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404

from django.http import FileResponse, HttpResponse
from reportlab.pdfgen import canvas
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.platypus import SimpleDocTemplate
import pandas as pd
from django.db.models import Q


class CreateUserView(APIView):
    def post(self, request, *args, **kwargs):
        User = get_user_model()
        data = request.data
        # Check if the request data is a list (for batch creation)
        if isinstance(data, list):
            users_created = []
            errors = []
            with transaction.atomic():
                for index, item in enumerate(data):
                    user_creation_result = self.create_user(item, User)
                    print(user_creation_result)
                    if "error" in user_creation_result:
                        errors.append(
                            {"index": index, "error": user_creation_result["error"]}
                        )
                    else:
                        users_created.append(user_creation_result["user"])
                if errors:
                    return Response(
                        {"errors": errors, "users_created": users_created},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                return Response(
                    {
                        "message": f"{len(users_created)} users created successfully",
                        "users": users_created,
                    },
                    status=status.HTTP_201_CREATED,
                )
        else:
            result = self.create_user(data, User)
            if "error" in result:
                return Response(
                    {"error": result["error"]}, status=status.HTTP_400_BAD_REQUEST
                )
            return Response(
                {"message": "User created successfully", "user": result["user"]},
                status=status.HTTP_201_CREATED,
            )

    def create_user(self, data, User):
        usn = data.get("usn")
        name = data.get("name")
        dob = data.get("dob")
        role = data.get("role")

        if not usn or not name or not dob:
            return Response(
                {"error": "USN, Name, and DOB are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            dob = datetime.strptime(dob, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"error": "Invalid DOB format, expected YYYY-MM-DD"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        department_name = data.get("department")
        if department_name:
            try:
                department = Department.objects.get(name=department_name)
            except Department.DoesNotExist:
                {"error": f"Department with name {department_name} does not exist"}
        else:
            return {"error": "Department name is required"}

        try:
            user = User.objects.create_user(
                usn=usn,
                name=name,
                dob=dob,
                role=role,
                semester=data.get("semester") if role == User.Role.STUDENT else None,
                department=department,
                password=data.get("password"),
            )
        except ValueError as e:
            return {"error": str(e)}

        return {"user": UserSerializer(user).data}


class CustomLoginView(APIView):
    def post(self, request, *args, **kwargs):
        usn = request.data.get("usn")
        password = request.data.get("password")

        if not usn or not password:
            return Response(
                {"error": "USN and passwordd are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        User = get_user_model()

        try:
            user = User.objects.get(usn=usn)
        except User.DoesNotExist:
            return Response(
                {"error": "User does not exist"}, status=status.HTTP_401_UNAUTHORIZED
            )

        # Check password
        if not user.check_password(password):
            print(password)
            return Response(
                {"error": "Wrong Password"}, status=status.HTTP_401_UNAUTHORIZED
            )

        token, created = Token.objects.get_or_create(user=user)
        user_serializer = UserSerializer(user).data

        res = Response(
            {
                "token": token.key,
                "role": user.role,
                "user": user_serializer,  # Include serialized user data in the response
            },
            status=status.HTTP_200_OK,
        )
        res.set_cookie("token", token.key, httponly=True)

        return res


class LogoutView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        request.auth.delete()  # Delete the Token
        return Response(status=status.HTTP_200_OK)


class SubjectViewSet(viewsets.ModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    authentication_classes = [TokenAuthentication]

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:  # Allow all users to list and retrieve
            permission_classes = [IsAuthenticated]
        else:  # Admin required for other actions
            permission_classes = [IsAuthenticated, IsAdminUser]
        return [permission() for permission in permission_classes]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())  # Use filtered queryset
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = SubjectSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExamViewSet(viewsets.ModelViewSet):
    queryset = Exam.objects.all()
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.user.is_staff:  # Assuming staff users are admins
            return AdminExamSerializer
        return StudentExamSerializer

    def create(self, request, *args, **kwargs):
        # Ensure that only ADMIN users can create exams
        if not request.user.role == User.Role.ADMIN:
            return Response(
                {"detail": "Only ADMIN users can create exams."},
                status=status.HTTP_403_FORBIDDEN,
            )
        # Deserialize the request data
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create the exam object with the provided data and the retrieved user
        exam = Exam(
            start_time=serializer.validated_data["start_time"],
            end_time=serializer.validated_data["end_time"],
            negativeMarks=serializer.validated_data["negativeMarks"],
            marksPerQuestion=serializer.validated_data["marksPerQuestion"],
            passingMarks=serializer.validated_data["passingMarks"],
            # Set the created_by field to the retrieved user
            created_by=serializer.validated_data["created_by"],
            department=serializer.validated_data["department"],
            subject=serializer.validated_data["subject"],
            semester=serializer.validated_data["semester"],
            duration=serializer.validated_data["duration"],
            is_published=serializer.validated_data.get("is_published", False),
            totalQuestions=serializer.validated_data["totalQuestions"],
            totalMarks=serializer.validated_data["totalMarks"],
        )

        # Save the exam object
        exam.save()

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def get_permissions(self):
        if self.action in ["list", "retrieve", "start_session", "end_session"]:
            # Using | (OR) operator to allow either students or admin
            self.permission_classes = [IsAuthenticated & (IsStudentUser | IsAdminUser)]
        else:  # For 'create', 'update', 'partial_update', 'destroy'
            self.permission_classes = [IsAuthenticated & IsAdminUser]
        return [permission() for permission in self.permission_classes]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        # Check if the user has permission to publish the exam
        if request.data.get("is_published", False):
            if not self.can_publish_exam(request.user, instance):
                return Response(
                    {"detail": "You do not have permission to publish this exam."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        self.perform_update(serializer)

        return Response(serializer.data)

    def can_publish_exam(self, user, exam):
        # Implement your permission logic here. For example:
        return user == exam.created_by or user.is_superuser

    def get_queryset(self):
        user = self.request.user
        if user.role == User.Role.STUDENT:
            user_semester = user.semester
            now = timezone.now()
            exams = Exam.objects.filter(
                semester=user_semester, end_time__gt=now, is_published=True
            )
            # Filter the attempted exams for the current user
            # attempted_exams = Result.objects.filter(student=user)
            attempted_exam_ids = Result.objects.filter(student=user).values_list(
                "exam_id", flat=True
            )
            # print(user_semester)
            print(exams)
            # print('attempted', attempted_exams)
            print("attempted", exams.exclude(id__in=attempted_exam_ids))
            # Exclude attempted exams from the queryset
            return exams.exclude(id__in=attempted_exam_ids)
        elif user.role == User.Role.ADMIN:
            return Exam.objects.all()
        else:
            return Exam.objects.none()

    @action(detail=True, methods=["post"])
    def start_session(self, request, pk=None):
        exam = self.get_object()

        if exam.has_ended():
            return Response(
                {"status": 0, "detail": "This exam has ended."},
                status=status.HTTP_200_OK,
            )
        if not exam.is_ongoing():
            return Response(
                {"detail": "This exam has not started yet."}, status=status.HTTP_200_OK
            )
        if ExamSession.objects.filter(
            exam=exam, student=request.user, end_time=None
        ).exists():
            return Response(
                {"detail": "You already have an active session for this exam."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        session = ExamSession.objects.create(exam=exam, student=request.user)
        return Response(
            {"detail": "Exam session started successfully.", "session_id": session.id}
        )

    @action(detail=True, methods=["post"])
    def end_session(self, request, pk=None):
        exam = self.get_object()
        session = get_object_or_404(
            ExamSession, exam=exam, student=request.user, end_time=None
        )
        session.end_time = timezone.now()
        session.save()
        return Response({"detail": "Exam session ended successfully."})

    @action(detail=True, methods=["get"])
    def active_sessions(self, request, pk=None):
        exam = self.get_object()
        active_sessions = ExamSession.objects.filter(exam=exam, end_time=None)
        serializer = ExamSessionSerializer(active_sessions, many=True)
        return Response(serializer.data)


class QuestionViewSet(viewsets.ModelViewSet):
    queryset = Question.objects.all()
    serializer_class = QuestionSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get_queryset(self):
        queryset = Question.objects.all()
        exam_id = self.request.query_params.get("exam", None)
        if exam_id is not None:
            queryset = queryset.filter(exam__id=exam_id)
        return queryset

    def create(self, request, *args, **kwargs):
        if isinstance(request.data, list):
            # Process each question in the list
            created_questions = []
            for question_data in request.data:
                question_text = question_data.get("text")
                subject_id = question_data.get("subject")
                choices = question_data.get("choices", [])

                # Check if a question with the same text, subject, and choices exists
                existing_question = Question.objects.filter(
                    text=question_text, subject_id=subject_id
                ).first()

                if existing_question:
                    # Check if choices also match
                    existing_choices = existing_question.choices.all()
                    if all(choice_data in existing_choices for choice_data in choices):
                        continue  # Skip this question as it's a duplicate

                # If not a duplicate, create a new question and choices
                serializer = self.get_serializer(data=question_data)
                if serializer.is_valid():
                    serializer.save()
                    created_question = serializer.data

                    # Include Choice IDs in the response
                    question_instance = Question.objects.get(pk=created_question["id"])
                    choices = ChoiceSerializer(
                        question_instance.choices.all(), many=True
                    ).data
                    created_question["choices"] = choices

                    created_questions.append(created_question)
                else:
                    print(serializer.errors)

            return Response(created_questions, status=status.HTTP_201_CREATED)
        else:
            return super(QuestionViewSet, self).create(request, *args, **kwargs)

    # @action(detail=True, methods=['patch'], parser_classes=[MultiPartParser, JSONParser])
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        print(request.data)
        serializer = self.get_serializer(instance, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            updated_instance = serializer.instance
            # Include Choice IDs in the response
            choices = ChoiceSerializer(updated_instance.choices.all(), many=True).data
            updated_data = serializer.data
            updated_data["choices"] = choices
            return Response(updated_data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class QuestionAssignmentViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = QuestionAssignmentSerializer

    def get_queryset(self):
        # Filter by the logged-in student and the provided exam id
        exam_id = self.kwargs.get("exam_id")
        return QuestionAssignment.objects.filter(
            student=self.request.user, exam__id=exam_id
        )


class DepartmentViewSet(viewsets.ModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]


class ChoiceViewSet(viewsets.ModelViewSet):
    queryset = Choice.objects.all()
    serializer_class = ChoiceSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def list(self, request, *args, **kwargs):
        queryset = Choice.objects.all()
        serializer = ChoiceSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = ChoiceSerializer(instance)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = ChoiceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = ChoiceSerializer(instance, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentAnswers(APIView):
    def post(self, request):
        data = request.data
        user_responses = data.get("answers", [])
        exam_id = data.get("exam_id", None)

        print(user_responses)
        #
        student = request.user  # Assuming your authentication is set up properly
        exam = Exam.objects.get(pk=exam_id)

        if not exam_id:
            return Response(
                {"error": "Exam ID not provided"}, status=status.HTTP_400_BAD_REQUEST
            )
        if Result.objects.filter(student=student, exam=exam).exists():
            res = Result.objects.filter(student=student, exam=exam)
            return Response(
                {
                    "error": "You have already attempted this exam",
                    "score": score,
                    "totalMarks": res.totalQuestions * res.marksPerQuestion,
                    "passingMarks": res.passingMarks,
                },
                status=status.HTTP_200_OK,
            )

        if user_responses == []:
            score = 0
            result_serializer = ResultSerializer(
                data={
                    "student": student.usn,
                    "exam": exam_id,
                    "totalMarks": exam.totalMarks,
                    "studentMarks": score,
                }
            )
            return Response(
                {
                    "score": score,
                    "totalMarks": exam.totalQuestions * exam.marksPerQuestion,
                    "passingMarks": exam.passingMarks,
                },
                status=status.HTTP_200_OK,
            )

        score = 0
        user_scored_answers = {}
        for user_response in user_responses:
            question_id = user_response.get("question_id")
            selected_choice_ids = user_response.get("selected_choices", [])

            # print(selected_choice_ids)
            try:
                question = Question.objects.get(pk=question_id)
            except Question.DoesNotExist:
                return Response(
                    {"error": f"Question with ID {question_id} does not exist"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            choices = Choice.objects.filter(question=question_id, is_correct=True)
            correct_choices = [c.id for c in choices]
            # print(set(selected_choice_ids) == set(correct_choices))
            print((correct_choices))

            # Use the serializer to create the StudentAnswers instance
            serializer = StudentAnswersSerializer(
                data={
                    "student": student.usn,
                    "exam": exam_id,
                    "question": question.id,
                    "selected_choices": selected_choice_ids,
                    "is_correct": set(selected_choice_ids) == set(correct_choices),
                }
            )
            if serializer.is_valid():
                serializer.save()

            # Check if the selected choices are correct for the question
            is_correct = set(selected_choice_ids) == set(correct_choices)

            # Calculate marks for the question based on correctness
            marks_for_question = (
                exam.marksPerQuestion if is_correct else -exam.negativeMarks
            )

            score += marks_for_question
            user_scored_answers[question_id] = {
                "is_correct": is_correct,
                "marks_for_question": marks_for_question,
            }

        # Use the serializer to create the Result instance
        result_serializer = ResultSerializer(
            data={
                "student": student.usn,
                "exam": exam_id,
                "totalMarks": exam.totalMarks,
                "studentMarks": score,
            }
        )
        if result_serializer.is_valid():
            result_serializer.save()

        # Send the evaluation results to the frontend
        response_data = {
            "score": score,
            # 'userScoredAnswers': user_scored_answers,
            "totalMarks": exam.totalQuestions * exam.marksPerQuestion,
            "passingMarks": exam.passingMarks,
        }
        return Response(response_data, status=status.HTTP_200_OK)


class UsersViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def create(self, request, *args, **kwargs):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = UserSerializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def list(self, request, *args, **kwargs):
        queryset = User.objects.all()
        serializer = UserSerializer(queryset, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = UserSerializer(instance)
        return Response(serializer.data)


class ReportViewSet(viewsets.ModelViewSet):
    @action(detail=True, methods=["get"])
    def generate_pdf_report(self, request, pk):
        data = Result.objects.filter(exam_id=pk).values_list(
            "student_id", "studentMarks"
        )

        buffer = BytesIO()
        pdf = SimpleDocTemplate(buffer, pagesize=letter)
        pdf_title = f"Student Marks Report - Exam ID: {pk}"
        table_data = [["Sl.no", "Student ID", "Marks"]] + [
            [i + 1, row[0], row[1]] for i, row in enumerate(data)
        ]

        style = TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
        table = Table(table_data, style=style)

        pdf_title += ""
        pdf.build([table])

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{pdf_title}.pdf"'
        buffer.seek(0)
        response.write(buffer.read())

        return response

    @action(detail=True, methods=["get"])
    def generate_excel_report(self, request, pk):
        # Fetch data from the database
        data = Result.objects.filter(exam_id=pk).values_list(
            "student_id", "studentMarks"
        )

        # Convert data to DataFrame
        columns = ["USN", "Marks"]
        df = pd.DataFrame(data, columns=columns)

        # Create a BytesIO buffer to write Excel file
        buffer = BytesIO()

        # Write DataFrame to Excel buffer
        df.to_excel(buffer, index=False, sheet_name="Student Marks")

        # Set the cursor to the beginning of the buffer
        buffer.seek(0)

        # Prepare HTTP response with the Excel file
        response = FileResponse(
            buffer, as_attachment=True, filename=f"student_marks_report_exam_{pk}.xlsx"
        )
        # response['Content-Disposition'] = f'attachment; filename="student_marks_report_exam_{pk}.xlsx"'
        # response.write(buffer.getvalue())

        return response

    @action(detail=True, methods=["get"])
    def generate_table_report(self, request, pk):
        response_data = []

        try:
            data = Result.objects.filter(exam_id=pk).select_related('student').values_list(
                "student_id", "student__name", "studentMarks")
        except Exception as e:
            print(e)

        for i,item in enumerate(data):
            item_dict = {
                "id": i+1,
                "usn": item[0],
                "name": item[1],
                "marks": item[2]
            }
            response_data.append(item_dict)
        # print(response_data)
        return Response(response_data, status=status.HTTP_200_OK)
