from typing import Any

from rest_framework import serializers

from sentry.api.fields.actor import ActorField
from sentry.api.serializers import Serializer, register, serialize
from sentry.api.serializers.models.rule import _generate_rule_label, _is_filter
from sentry.api.serializers.rest_framework.base import ModelSerializer
from sentry.api.serializers.rest_framework.rule import (
    RuleNodeField,
    RuleSetSerializer,
    validate_actions,
)
from sentry.blueprint.models import AlertProcedure, AlertTemplate
from sentry.models.actor import ACTOR_TYPES
from sentry.models.project import Project
from sentry.models.rule import Rule
from sentry.models.user import User


@register(AlertProcedure)
class AlertProcedureSerializer(Serializer):
    def serialize(self, obj: AlertProcedure, attrs: Any, user: User, **kwargs):
        # TODO(Leander): Use get_attrs
        templates = AlertTemplate.objects.filter(procedure_id=obj.id)

        # XXX: Hack to avoid unravelling the project dependency :(
        project = Project.objects.filter(organization=obj.organization).first()
        actions = []
        for action in obj.issue_alert_actions:
            try:
                actions.append(
                    dict(
                        list(action.items())
                        + [("name", _generate_rule_label(project, obj, action))]
                    )
                )
            except serializers.ValidationError:
                # Integrations can be deleted and we don't want to fail to load the rule
                pass

        owner_value = None
        if obj.owner_id and obj.owner.type == ACTOR_TYPES["team"]:
            owner_value = f"team:{obj.owner.team_id}"
        if obj.owner_id and obj.owner.type == ACTOR_TYPES["user"]:
            owner_value = f"user:{obj.owner.user_id}"
        return {
            "id": str(obj.id),
            # TODO(Leander): Use a better serializer or expand
            "owner": owner_value,
            "templates": [{"id": t.id, "name": t.name} for t in templates],
            "label": obj.label,
            "organization_id": obj.organization_id,
            "is_manual": obj.is_manual,
            "issue_alert_actions": actions,
        }


class IncomingAlertProcedureSerializer(ModelSerializer):
    """
    context: organization, project, procedure_id
    """

    label = serializers.CharField(max_length=255)
    owner = ActorField(required=False, allow_null=True)
    is_manual = serializers.BooleanField(default=False)
    issue_alert_actions = serializers.ListField(
        child=RuleNodeField(type="action/event"), required=False
    )

    class Meta:
        model = AlertProcedure
        fields = [
            "label",
            "owner",
            "is_manual",
            "issue_alert_actions",
        ]

    def validate_label(self, incoming_label: str):
        existing_id = self.context.get("procedure_id")
        procedure_qs = AlertProcedure.objects.filter(
            organization_id=self.context["organization"].id, label=incoming_label
        )
        if existing_id:
            procedure_qs = procedure_qs.exclude(id=existing_id)
        if procedure_qs.exists():
            raise serializers.ValidationError(
                detail="Choose a better label nerd, that one's taken."
            )
        return incoming_label

    def validate_owner(self, owner):
        return owner.resolve_to_actor()

    def validate(self, attrs):
        return validate_actions(attrs)

    def create(self, validated_data):
        return AlertProcedure.objects.create(
            organization_id=self.context["organization"].id,
            **validated_data,
        )


@register(AlertTemplate)
class AlertTemplateSerializer(Serializer):
    def serialize(self, obj: AlertTemplate, attrs: Any, user: User, **kwargs):
        # XXX: Hack to avoid unravelling the project dependency :(
        project = Project.objects.filter(organization=obj.organization).first()

        all_conditions = [
            dict(list(o.items()) + [("name", _generate_rule_label(project, obj, o))])
            for o in obj.issue_alert_data.get("conditions", [])
        ]
        issue_alert_data = {
            # conditions pertain to criteria that can trigger an alert
            "conditions": list(filter(lambda condition: not _is_filter(condition), all_conditions)),
            # filters are not new conditions but are the subset of conditions that pertain to event attributes
            "filters": list(filter(lambda condition: _is_filter(condition), all_conditions)),
            "actionMatch": obj.issue_alert_data.get("action_match") or Rule.DEFAULT_CONDITION_MATCH,
            "filterMatch": obj.issue_alert_data.get("filter_match") or Rule.DEFAULT_FILTER_MATCH,
            "frequency": obj.issue_alert_data.get("frequency") or Rule.DEFAULT_FREQUENCY,
        }
        rules = Rule.objects.filter(template_id=obj.id)
        owner_value = None
        if obj.owner_id and obj.owner.type == ACTOR_TYPES["team"]:
            owner_value = f"team:{obj.owner.team_id}"
        if obj.owner_id and obj.owner.type == ACTOR_TYPES["user"]:
            owner_value = f"user:{obj.owner.user_id}"

        return {
            "id": str(obj.id),
            "owner": owner_value,
            "name": obj.name,
            "organization_id": obj.organization_id,
            # TODO(Leander): Use get_attrs
            "issue_alert_ids": [r.id for r in rules],
            "issue_alert_data": issue_alert_data,
            "procedure": serialize(obj.procedure),
        }


class IncomingAlertTemplateSerializer(ModelSerializer):
    """
    context: organization, project, procedure_id, template_id,
    """

    name = serializers.CharField(max_length=128)
    owner = ActorField(required=False, allow_null=True)
    issue_alerts = serializers.ListField(child=serializers.IntegerField(), required=False)
    issue_alert_data = RuleSetSerializer(partial=True)
    issue_alert_actions = serializers.ListField(
        child=RuleNodeField(type="action/event"), required=False
    )

    class Meta:
        model = AlertProcedure
        fields = [
            "name",
            "owner",
            "issue_alerts",
            "issue_alert_data",
            "issue_alert_actions",
        ]

    def validate_name(self, incoming_name: str):
        existing_id = self.context.get("template_id")
        template_qs = AlertTemplate.objects.filter(
            organization_id=self.context["organization"].id, name=incoming_name
        )
        if existing_id:
            template_qs = template_qs.exclude(id=existing_id)
        if template_qs.exists():
            raise serializers.ValidationError(detail="Choose a better name nerd, that one's taken.")
        return incoming_name

    def validate_issue_alerts(self, incoming_issue_alerts):
        issue_alerts = Rule.objects.filter(
            id__in=incoming_issue_alerts, project__organization_id=self.context["organization"].id
        )
        if len(issue_alerts) != len(incoming_issue_alerts):
            raise serializers.ValidationError(
                detail="Not all provided issue alerts are available to this organization."
            )
        return incoming_issue_alerts

    def validate_owner(self, owner):
        return owner.resolve_to_actor()

    def validate(self, attrs):
        return validate_actions(attrs)

    def _create_alert_procedure(self, validated_data) -> AlertProcedure:
        name = validated_data["name"]
        issue_alert_actions = validated_data.pop("issue_alert_actions", [])
        procedure_data = {
            "label": f"[Procedure from Template] {name}",
            "issue_alert_actions": issue_alert_actions,
        }
        serializer = IncomingAlertProcedureSerializer(
            data=procedure_data,
            context={
                "organization": self.context["organization"],
                "project": self.context["project"],
            },
        )
        if serializer.is_valid(raise_exception=True):
            ap = serializer.save()
            return ap

    def create(self, validated_data):
        procedure_id = self.context.get("procedure_id")
        if validated_data.get("issue_alert_actions"):
            ap = self._create_alert_procedure(validated_data=validated_data)
            procedure_id = ap.id

        issue_alerts = validated_data.pop("issue_alerts", [])
        at = AlertTemplate.objects.create(
            organization_id=self.context["organization"].id,
            procedure_id=procedure_id,
            **validated_data,
        )
        if len(issue_alerts) > 0:
            Rule.objects.filter(id__in=issue_alerts).update(template_id=at.id)

        return at
