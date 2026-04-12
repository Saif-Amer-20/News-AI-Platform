from __future__ import annotations

import re

from topics.models import KeywordRule, Topic


class TopicMatchingService:
    def match(self, article):
        haystacks = {
            KeywordRule.MatchTarget.ANY: f"{article.normalized_title} {article.normalized_content} {article.canonical_url}",
            KeywordRule.MatchTarget.TITLE: article.normalized_title,
            KeywordRule.MatchTarget.BODY: article.normalized_content,
            KeywordRule.MatchTarget.URL: article.canonical_url.lower(),
        }

        matched_topics: set[int] = set()
        matched_rule_labels: set[str] = set()
        exclusion_topics: set[int] = set()

        rules = KeywordRule.objects.select_related("topic").filter(enabled=True)
        for rule in rules:
            haystack = haystacks.get(rule.match_target) or haystacks[KeywordRule.MatchTarget.ANY]
            if not self._matches(rule, haystack):
                continue
            if rule.is_exclusion:
                exclusion_topics.add(rule.topic_id)
                continue
            matched_topics.add(rule.topic_id)
            matched_rule_labels.add(rule.label)

        matched_topics -= exclusion_topics
        article.matched_topics.set(Topic.objects.filter(id__in=matched_topics))
        article.matched_rule_labels = sorted(matched_rule_labels)
        article.save(update_fields=["matched_rule_labels", "updated_at"])
        return article

    def _matches(self, rule: KeywordRule, haystack: str) -> bool:
        pattern = rule.pattern if rule.case_sensitive else rule.pattern.lower()
        target = haystack if rule.case_sensitive else haystack.lower()

        if rule.rule_type in {KeywordRule.RuleType.KEYWORD, KeywordRule.RuleType.PHRASE}:
            return pattern in target
        if rule.rule_type == KeywordRule.RuleType.REGEX:
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            return re.search(rule.pattern, haystack, flags=flags) is not None
        if rule.rule_type == KeywordRule.RuleType.BOOLEAN:
            return self._boolean_match(pattern, target)
        return False

    def _boolean_match(self, pattern: str, target: str) -> bool:
        or_groups = [group.strip() for group in pattern.split(" OR ")]
        for group in or_groups:
            and_terms = [term.strip() for term in group.split(" AND ") if term.strip()]
            if and_terms and all(term in target for term in and_terms):
                return True
        return False
