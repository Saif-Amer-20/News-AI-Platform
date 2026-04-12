from __future__ import annotations

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from services.orchestration.ingest_orchestration import IngestOrchestrationService
from sources.tasks import process_raw_item_task

from .serializers import ProcessRawItemSerializer


class ProcessRawItemView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = ProcessRawItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        raw_item_id = serializer.validated_data["raw_item_id"]
        run_inline = serializer.validated_data["sync"]

        if run_inline:
            article = IngestOrchestrationService().process_raw_item(raw_item_id)
            return Response(
                {
                    "status": "processed",
                    "raw_item_id": raw_item_id,
                    "article_id": article.id if article else None,
                },
                status=status.HTTP_200_OK,
            )

        async_result = process_raw_item_task.delay(raw_item_id)
        return Response(
            {
                "status": "queued",
                "raw_item_id": raw_item_id,
                "task_id": async_result.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )
