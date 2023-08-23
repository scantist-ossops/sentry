from collections import defaultdict

from django.utils.text import slugify
from iniconfig import ParseError
from rest_framework import serializers, status

from sentry.api.bases.organization import NoProjects, OrganizationEndpoint
from sentry.api.bases.organization_events import OrganizationEventsV2EndpointBase
from sentry.api.serializers import serialize
from sentry.api.serializers.models.funnel import FunnelSerializer
from sentry.api.serializers.models.group import GroupSerializerSnuba
from sentry.api.serializers.models.group_stream import StreamGroupSerializerSnuba
from sentry.api.serializers.rest_framework.base import CamelSnakeSerializer
from sentry.api.utils import InvalidParams
from sentry.models.funnel import Funnel
from sentry.models.group import Group
from sentry.snuba.referrer import Referrer
from sentry.utils import json


def get_issues_from_users(users, dataset, query, snuba_params, params):
    userquery = " OR ".join([f"user:{user}" for user in users])
    print(userquery)
    ret = dataset.query(
        selected_columns=["issue", "timestamp", "user", "count()"],
        query=f"{userquery} AND ({query})",
        params=params,
        snuba_params=snuba_params,
        equations=[],
        orderby="",
        offset=0,
        limit=50,
        auto_fields=True,
        auto_aggregations=True,
        use_aggregate_conditions=True,
        allow_metric_aggregates=False,
        transform_alias_to_input_format=True,
        # Whether the flag is enabled or not, regardless of the referrer
        has_metrics=False,
        use_metrics_layer=False,
        on_demand_metrics_enabled=False,
        referrer=Referrer.API_ORGANIZATION_EVENTS_V2.value,
    )["data"]

    # get all the group ids and fetch from Postgres
    group_ids = [issue["issue.id"] for issue in ret]
    groups = Group.objects.filter(id__in=group_ids)

    users_by_issue = defaultdict(set)
    issues_by_id = {}
    for issue in ret:
        users_by_issue[str(issue["issue.id"])].add(issue["user"])
        issues_by_id[str(issue["issue.id"])] = groups.get(id=issue["issue.id"])

    return users_by_issue, issues_by_id


class FunnelDetailsEndpoint(OrganizationEventsV2EndpointBase):
    def get(self, request, organization, funnel_slug):

        funnel = Funnel.objects.get(slug=funnel_slug)
        starting_transaction = funnel.starting_transaction
        ending_transaction = funnel.ending_transaction

        # TODO: figure out how to handle the project id
        try:
            snuba_params, params = self.get_snuba_dataclass(request, organization)
        except NoProjects:
            return self.respond(
                {
                    "data": [],
                    "meta": {
                        "tips": {
                            "query": "Need at least one valid project to query.",
                        },
                    },
                }
            )
        except InvalidParams as err:
            raise ParseError(err)

        dataset = self.get_dataset(request)
        query = f"transaction:{starting_transaction} OR transaction:{ending_transaction}"
        response = dataset.query(
            selected_columns=["user", "transaction", "timestamp"],
            query=query,
            params=params,
            snuba_params=snuba_params,
            equations=[],
            orderby=self.get_orderby(request),
            offset=0,
            limit=50,
            auto_fields=True,
            auto_aggregations=True,
            use_aggregate_conditions=True,
            allow_metric_aggregates=False,
            transform_alias_to_input_format=True,
            # Whether the flag is enabled or not, regardless of the referrer
            has_metrics=False,
            use_metrics_layer=False,
            on_demand_metrics_enabled=False,
            referrer=Referrer.API_ORGANIZATION_EVENTS_V2.value,
        )

        min_start_time_per_user = {}
        max_end_time_per_user = {}
        for transaction in response["data"]:
            if transaction["transaction"] == starting_transaction:
                min_start_time_per_user[transaction["user"]] = min(
                    min_start_time_per_user.get(transaction["user"], transaction["timestamp"]),
                    transaction["timestamp"],
                )
            elif transaction["transaction"] == ending_transaction:
                max_end_time_per_user[transaction["user"]] = max(
                    max_end_time_per_user.get(transaction["user"], transaction["timestamp"]),
                    transaction["timestamp"],
                )

        total_starts = 0
        total_completions = 0
        for user, min_start_time in min_start_time_per_user.items():
            total_starts += 1
            if user in max_end_time_per_user:
                if max_end_time_per_user[user] > min_start_time:
                    total_completions += 1

        allusers = [*min_start_time_per_user.keys(), *max_end_time_per_user.keys()]
        users_by_issue_id, issues_by_id = get_issues_from_users(
            allusers, dataset, query, snuba_params, params
        )
        print(users_by_issue_id)
        retissues = {}
        for issue, users in users_by_issue_id.items():
            starts = 0
            completes = 0
            for user in users:
                if user in min_start_time_per_user.keys():
                    starts += 1
                    if user in max_end_time_per_user.keys():
                        completes += 1

            print(issue, starts, completes)
            retissues[issue] = {"starts": starts, "completes": completes}

        issues = serialize(
            list(issues_by_id.values()),
            request.user,
            serializer=StreamGroupSerializerSnuba(
                organization_id=organization.id,
                project_ids=request.GET.getlist("project"),
            ),
        )
        print("issues", issues, retissues)
        issues_with_data = []
        for issue in issues:
            if issue["id"] in retissues:
                data = {
                    "starts": retissues[issue["id"]]["starts"],
                    "completes": retissues[issue["id"]]["completes"],
                    "issue": issue,
                }
                issues_with_data.append(data)
        print(issues_with_data)
        return self.respond(
            {
                "totalStarts": total_starts,
                "totalCompletions": total_completions,
                "funnel": serialize(funnel, request.user, serializer=FunnelSerializer()),
                "issues": issues_with_data,
            },
            status=200,
        )

    def delete(self, request, organization, funnel_slug):
        funnel = Funnel.objects.get(slug=funnel_slug)
        funnel.delete()
        return self.respond(status=204)