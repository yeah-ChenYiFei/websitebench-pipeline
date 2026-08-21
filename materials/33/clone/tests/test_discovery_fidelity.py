"""Source-identity contracts for the public subject landing pages."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import app
from home_inventory import load_home_inventory


client = TestClient(app)


CURRENT_HOME_IDENTITIES = {
    "most-popular": (
        ("Google Data Analytics", "Google", "/professional-certificates/google-data-analytics"),
        ("Foundations: Data, Data, Everywhere", "Google", "/learn/foundations-data"),
        ("Python for Everybody", "University of Michigan", "/specializations/python"),
    ),
    "hot-new-releases": (
        ("Microsoft Junior QA/Software Tester", "Microsoft", "/professional-certificates/microsoft-junior-qa-software-tester"),
        ("IBM Financial Planning and Analysis (FP&A) with AI Skills", "IBM", "/professional-certificates/ibm-financial-planning-analysis-ai-skills"),
        ("Business Analytics with Excel", "Johns Hopkins University", "/specializations/business-analytics-with-excel"),
    ),
    "trending-ai-courses": (
        ("AI for Brainstorming and Planning", "Google", "/learn/google-ai-for-brainstorming-and-planning"),
        ("Generative AI Software Engineering", "Vanderbilt University", "/specializations/generative-ai-software-engineering"),
        ("AI in Healthcare", "Stanford Online", "/specializations/ai-healthcare"),
    ),
    "career-data": (
        ("Google Data Analytics", "Google", "/professional-certificates/google-data-analytics"),
        ("Microsoft Power BI Data Analyst", "Microsoft", "/professional-certificates/microsoft-power-bi-data-analyst"),
        ("IBM Data Science", "IBM", "/professional-certificates/ibm-data-science"),
        ("Tableau Business Intelligence Analyst", "Tableau Learning Partner", "/professional-certificates/tableau-business-intelligence-analyst"),
    ),
    "google-career": (
        ("Google AI Essentials", "Google", "/specializations/ai-essentials-google"),
        ("Google Advanced Data Analytics", "Google", "/professional-certificates/google-advanced-data-analytics"),
        ("Google Project Management", "Google", "/professional-certificates/google-project-management"),
        ("Google Cybersecurity", "Google", "/professional-certificates/google-cybersecurity"),
    ),
    "trending-python": (
        ("Python for Everybody", "University of Michigan", "/specializations/python"),
        ("Python 3 Programming", "University of Michigan", "/specializations/python-3-programming"),
        ("Data Analysis with Pandas and Python", "Packt", "/specializations/packt-data-analysis-with-pandas-and-python"),
    ),
    "trending-data-analytics": (
        ("Excel Skills for Business", "Macquarie University", "/specializations/excel"),
        ("IBM Data Analyst", "IBM", "/professional-certificates/ibm-data-analyst"),
        ("Google Advanced Data Analytics", "Google", "/professional-certificates/google-advanced-data-analytics"),
    ),
    "trending-project-management": (
        ("Foundations of Project Management", "Google", "/learn/project-management-foundations"),
        ("IBM Project Manager", "IBM", "/professional-certificates/ibm-project-manager"),
        ("Microsoft Project Management: Build Job-Ready Skills", "Microsoft", "/professional-certificates/microsoft-project-management"),
    ),
    "ai-skills": (
        ("Google AI Essentials", "Google", "/specializations/ai-essentials-google"),
        ("AI Foundations for Everyone", "IBM", "/specializations/ai-foundations-for-everyone"),
        ("Prompt Engineering", "Vanderbilt University", "/specializations/prompt-engineering"),
        ("Google Prompting Essentials", "Google", "/specializations/prompting-essentials-google"),
    ),
    "explore-careers": (
        ("Data Scientist", "", "/career-academy/roles/data-scientist"),
        ("Machine Learning Engineer", "", "/career-academy/roles/machine-learning-engineer"),
        ("Content Creator", "", "/career-academy/roles/content-creator"),
        ("Data Analyst", "", "/career-academy/roles/data-analyst"),
        ("Business Intelligence Analyst", "", "/career-academy/roles/business-intelligence-analyst"),
    ),
}


def test_current_home_inventory_preserves_frozen_card_identity_and_order() -> None:
    sections = load_home_inventory()

    assert tuple(section.section_id for section in sections) == tuple(CURRENT_HOME_IDENTITIES)
    for section in sections:
        actual = tuple((card.title, card.provider, card.href) for card in section.cards)
        assert actual == CURRENT_HOME_IDENTITIES[section.section_id]
        assert tuple(card.position for card in section.cards) == tuple(range(len(section.cards)))
        assert all(card.image.startswith("/static/home/cards/") for card in section.cards)
        assert all("/static/browse/" not in card.image for card in section.cards)
        assert all("/static/data-science/" not in card.image for card in section.cards)


SOURCE_CATEGORY_CARDS = {
    "arts-and-humanities": (
        ("Graphic Design", "California Institute of the Arts", "4.7", "22K reviews", "Beginner · Specialization"),
        ("Modern and Contemporary Art and Design", "The Museum of Modern Art", "4.8", "12K reviews", "Beginner · Specialization"),
        ("Fundamentals of Graphic Design", "California Institute of the Arts", "4.8", "18K reviews", "Beginner · Course · 4 weeks of study, 5-8 hours/week"),
        ("Indigenous Canada", "University of Alberta", "4.8", "24K reviews", "Beginner · Course · 12 weeks, 2-3 hours a week."),
    ),
    "computer-science": (
        ("Python for Everybody", "University of Michigan", "4.8", "281K reviews", "Beginner · Specialization"),
        ("Programming for Everybody (Getting Started with Python)", "University of Michigan", "4.8", "234K reviews", "Beginner · Course · 2-4 hours/week"),
        ("IBM AI Developer", "IBM", "4.7", "83K reviews", "Beginner · Professional Certificate"),
        ("IBM DevOps and Software Engineering", "IBM", "4.6", "66K reviews", "Beginner · Professional Certificate · 3 months"),
    ),
    "health": (
        ("Introduction to Psychology", "Yale University", "4.9", "33K reviews", "Beginner · Course"),
        ("Stanford Introduction to Food and Health", "Stanford Online", "4.7", "34K reviews", "Beginner · Course · 5 weeks of study, 1 hour/week"),
        ("Social Psychology", "Wesleyan University", "4.7", "5.2K reviews", "Beginner · Course · 6 weeks of study, 4-6 hours/week (plus a mid-course break)"),
        ("Writing in the Sciences", "Stanford Online", "4.9", "9.8K reviews", "Beginner · Course · 8 weeks of study, 3-5 hours/week"),
    ),
    "information-technology": (
        ("Google IT Support", "Google", "4.8", "215K reviews", "Beginner · Professional Certificate"),
        ("IBM Full Stack Software Developer", "IBM", "4.6", "61K reviews", "Beginner · Professional Certificate"),
        ("Technical Support Fundamentals", "Google", "4.8", "165K reviews", "Beginner · Course · 8-10 hours per module"),
        ("IBM Data Engineering", "IBM", "4.6", "63K reviews", "Beginner · Professional Certificate · 5 months"),
    ),
    "language-learning": (
        ("Improve Your English Communication Skills", "Georgia Institute of Technology", "4.7", "27K reviews", "Beginner · Specialization"),
        ("First Step Korean", "Yonsei University", "4.9", "54K reviews", "Beginner · Course · 5 weeks of study, 1-3 hours/week"),
        ("Étudier en France: French Intermediate course B1-B2", "École Polytechnique", "4.8", "5.2K reviews", "Intermediate · Course · 6 semaines, 5 à 7 heures par semaine"),
        ("Learn to Speak Korean 1", "Yonsei University", "4.9", "12K reviews", "Beginner · Course · 6 weeks of study, 2-4 hours/week"),
    ),
    "math-and-logic": (
        ("Introduction to Mathematical Thinking", "Stanford Online", "4.8", "3K reviews", "Intermediate · Course · Expect to require at least 10 hours of study per week to complete this course satisfactorily."),
        ("Data Science Math Skills", "Duke University", "4.5", "13K reviews", "Beginner · Course · Four weeks, 3-5 hours per week."),
        ("Introduction to Calculus", "The University of Sydney", "4.8", "4K reviews", "Intermediate · Course"),
        ("Introduction to Logic", "Stanford Online", "4.4", "656 reviews", "Intermediate · Course · 10 weeks of study, 4-8 hours/week"),
    ),
    "personal-development": (
        ("Learning How to Learn: Powerful mental tools to help you master tough subjects", "Deep Teaching Solutions", "4.8", "93K reviews", "Beginner · Course · about 3 hours of video, 3 hours of exercises, 3 hours of bonus material"),
        ("Accelerate Your Job Search with AI", "Google", "4.8", "6K reviews", "Beginner · Course"),
        ("Mindshift: Break Through Obstacles to Learning and Discover Your Hidden Potential", "McMaster University", "4.8", "13K reviews", "Beginner · Course · Two hours of study per week, for four weeks."),
        ("Creative Thinking: Techniques and Tools for Success", "Imperial College London", "4.7", "5.2K reviews", "Beginner · Course · 2-4 hours/week"),
    ),
    "physical-science-and-engineering": (
        ("An Introduction to Programming the Internet of Things (IOT)", "University of California, Irvine", "4.7", "21K reviews", "Beginner · Specialization"),
        ("How Things Work: An Introduction to Physics", "University of Virginia", "4.8", "3.1K reviews", "Intermediate · Course · 11 hours of videos and assessments"),
        ("Robótica", "Universidad Nacional Autónoma de México", "4.5", "1.5K reviews", "Beginner · Course · 5 semanas de estudio, 2-4 horas/semana"),
        ("Astronomy: Exploring Time and Space", "University of Arizona", "4.8", "4K reviews", "Beginner · Course · ~26 hours of lectures and assignments"),
    ),
    "social-sciences": (
        ("Academic English: Writing", "University of California, Irvine", "4.7", "23K reviews", "Beginner · Specialization"),
        ("Generative AI for Educators", "IBM", "4.7", "12K reviews", "Beginner · Specialization · 1 month"),
        ("Prompt Engineering for Educators", "Vanderbilt University", "4.8", "8.8K reviews", "Beginner · Specialization"),
        ("Generative AI and ChatGPT for K-12 Educators", "Vanderbilt University", "4.8", "8.8K reviews", "Beginner · Specialization"),
    ),
}


@pytest.mark.parametrize("slug", SOURCE_CATEGORY_CARDS)
def test_category_cards_match_the_four_source_records_in_order(slug: str) -> None:
    """Catch inferred cards, stale ratings, or metadata crossing card boundaries."""

    response = client.get(f"/browse/{slug}")
    cards = re.findall(
        r'<article class="source-category-card"[^>]*>(.*?)</article>',
        response.text,
        flags=re.DOTALL,
    )

    assert response.status_code == 200
    assert len(cards) == 4
    for card_html, expected_fields in zip(cards, SOURCE_CATEGORY_CARDS[slug]):
        for expected in expected_fields:
            assert expected in card_html


@pytest.mark.parametrize(
    ("slug", "roles_expected", "faq_expected"),
    (
        ("arts-and-humanities", True, True),
        ("computer-science", True, True),
        ("health", False, True),
        ("information-technology", True, True),
        ("language-learning", False, True),
        ("math-and-logic", False, False),
        ("personal-development", False, True),
        ("physical-science-and-engineering", False, True),
        ("social-sciences", False, True),
    ),
)
def test_category_lower_sections_follow_the_source_route(
    slug: str, roles_expected: bool, faq_expected: bool
) -> None:
    """Catch one generic lower-page template inventing sections on every subject."""

    html = client.get(f"/browse/{slug}").text

    assert ('class="source-category-roles"' in html) is roles_expected
    assert ('class="source-category-faq"' in html) is faq_expected
