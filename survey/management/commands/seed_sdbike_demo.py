from django.contrib.auth import get_user_model
from django.contrib.gis.geos import LineString, Point
from django.core.management.base import BaseCommand
from django.utils import timezone

from survey.models import (
    Answer,
    Membership,
    Organization,
    Question,
    Story,
    SurveyHeader,
    SurveySection,
)


class Command(BaseCommand):
    help = "Create the San Diego County Bicycle Coalition demo survey."

    def handle(self, *args, **options):
        User = get_user_model()
        user, _ = User.objects.get_or_create(
            username="sdbike_admin",
            defaults={
                "email": "demo@sdbikecoalition.org",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if not user.has_usable_password():
            user.set_password("sdbike-demo-admin")
            user.save(update_fields=["password"])

        org, _ = Organization.objects.get_or_create(
            slug="san-diego-county-bicycle-coalition",
            defaults={"name": "San Diego County Bicycle Coalition"},
        )
        Membership.objects.get_or_create(
            user=user,
            organization=org,
            defaults={"role": "owner"},
        )

        survey, _ = SurveyHeader.objects.update_or_create(
            name="bike_for_better_sd",
            defaults={
                "organization": org,
                "created_by": user,
                "visibility": "demo",
                "status": "published",
                "redirect_url": "#",
                "thanks_html": {
                    "en": (
                        "<h1>Thanks for mapping a better ride.</h1>"
                        "<p>Your input helps identify safer school routes, "
                        "missing bikeway links, dangerous crossings, and "
                        "places where bike parking or education can help.</p>"
                    )
                },
                "validation_settings": {
                    "fast_threshold_seconds": 30,
                    "duplicate_window_hours": 24,
                },
            },
        )

        SurveySection.objects.filter(survey_header=survey).delete()

        center = Point(-117.1611, 32.7157)
        intro = SurveySection.objects.create(
            survey_header=survey,
            name="start",
            title="Bike for a Better San Diego",
            subheading=(
                "Tell us where biking feels unsafe, where the network breaks, "
                "and which short trips you would make by bike with better streets."
            ),
            code="START",
            is_head=True,
            start_map_postion=center,
            start_map_zoom=11,
            use_geolocation=True,
        )
        safety = SurveySection.objects.create(
            survey_header=survey,
            name="safety",
            title="Mark safety concerns",
            subheading="Drop pins at dangerous crossings, near misses, or streets that keep people from riding.",
            code="SAFE",
            start_map_postion=center,
            start_map_zoom=12,
            use_geolocation=True,
        )
        routes = SurveySection.objects.create(
            survey_header=survey,
            name="routes",
            title="Draw the routes San Diego needs",
            subheading="Draw a route you ride now, avoid today, or would ride if a connected bikeway existed.",
            code="ROUTE",
            start_map_postion=center,
            start_map_zoom=11,
            use_geolocation=True,
        )
        priorities = SurveySection.objects.create(
            survey_header=survey,
            name="priorities",
            title="Set advocacy priorities",
            subheading="Help the Coalition turn mapped feedback into campaigns, classes, and partner asks.",
            code="PRIOR",
            start_map_postion=center,
            start_map_zoom=10,
            use_geolocation=False,
        )

        intro.next_section = safety
        safety.prev_section = intro
        safety.next_section = routes
        routes.prev_section = safety
        routes.next_section = priorities
        priorities.prev_section = routes
        intro.save()
        safety.save()
        routes.save()
        priorities.save()

        def add_question(section, order, code, name, input_type, **kwargs):
            return Question.objects.create(
                survey_section=section,
                order_number=order,
                code=code,
                name=name,
                input_type=input_type,
                **kwargs,
            )

        rider_type = add_question(
            intro,
            1,
            "Q_RIDER_TYPE",
            "Which best describes you?",
            "multichoice",
            required=True,
            choices=[
                {"code": 1, "name": "I ride for transportation"},
                {"code": 2, "name": "I ride for recreation"},
                {"code": 3, "name": "I ride with kids or students"},
                {"code": 4, "name": "I do not ride now, but I want to"},
                {"code": 5, "name": "I use or am curious about e-bikes"},
            ],
        )
        home_area = add_question(
            intro,
            2,
            "Q_HOME_AREA",
            "What neighborhood or city should we understand?",
            "text_line",
            required=True,
        )
        hazard = add_question(
            safety,
            1,
            "Q_HAZARD_PIN",
            "Mark a place that feels unsafe by bike.",
            "point",
            required=True,
            subtext="Click this card, then click the map to drop a pin.",
            color="#d8534f",
            icon_class="fas fa-exclamation-triangle",
        )
        hazard_type = add_question(
            safety,
            2,
            "Q_HAZARD_TYPE",
            "What is the main issue here?",
            "choice",
            parent_question_id=hazard,
            required=True,
            choices=[
                {"code": 1, "name": "High-speed traffic"},
                {"code": 2, "name": "Unsafe intersection or crossing"},
                {"code": 3, "name": "Missing bike lane or protection"},
                {"code": 4, "name": "Door zone, parking, or loading conflict"},
                {"code": 5, "name": "Other"},
            ],
        )
        hazard_note = add_question(
            safety,
            3,
            "Q_HAZARD_NOTE",
            "Add a short note for advocates.",
            "text",
            parent_question_id=hazard,
        )
        route = add_question(
            routes,
            1,
            "Q_ROUTE_LINE",
            "Draw a route or missing bikeway link.",
            "line",
            required=True,
            color="#2f6fb4",
            icon_class="fas fa-bicycle",
        )
        route_purpose = add_question(
            routes,
            2,
            "Q_ROUTE_PURPOSE",
            "What would this route connect?",
            "multichoice",
            parent_question_id=route,
            choices=[
                {"code": 1, "name": "School"},
                {"code": 2, "name": "Transit"},
                {"code": 3, "name": "Work"},
                {"code": 4, "name": "Parks or beaches"},
                {"code": 5, "name": "Shops or errands"},
            ],
        )
        top_priority = add_question(
            priorities,
            1,
            "Q_TOP_PRIORITY",
            "What should the Coalition push for first?",
            "choice",
            required=True,
            choices=[
                {"code": 1, "name": "Fix dangerous intersections near schools"},
                {"code": 2, "name": "Build continuous all-ages bikeways"},
                {"code": 3, "name": "Expand secure bike parking"},
                {"code": 4, "name": "Launch more bike buses and classes"},
                {"code": 5, "name": "Bring back county-wide bikeshare"},
            ],
        )
        trip_shift = add_question(
            priorities,
            2,
            "Q_TRIP_SHIFT",
            "How many weekly car trips could you replace by bike if these changes happened?",
            "range",
            choices=[
                {"code": 0, "name": "0"},
                {"code": 1, "name": "1"},
                {"code": 2, "name": "2"},
                {"code": 3, "name": "3"},
                {"code": 4, "name": "4"},
                {"code": 5, "name": "5+"},
            ],
        )
        contact = add_question(
            priorities,
            3,
            "Q_CONTACT",
            "Optional: email if you want to help with follow-up advocacy.",
            "text_line",
        )

        Story.objects.update_or_create(
            slug="bike-for-a-better-san-diego",
            defaults={
                "title": "Bike for a Better San Diego",
                "body": (
                    "This demo turns open-source Mapsurvey into a county-wide "
                    "bike engagement hub for Vision Zero, connected bikeways, "
                    "bike education, and mode shift campaigns."
                ),
                "story_type": "map",
                "survey": survey,
                "is_published": True,
                "published_date": timezone.now(),
            },
        )

        self._seed_sample_responses(
            survey,
            {
                "rider_type": rider_type,
                "home_area": home_area,
                "hazard": hazard,
                "hazard_type": hazard_type,
                "hazard_note": hazard_note,
                "route": route,
                "route_purpose": route_purpose,
                "top_priority": top_priority,
                "trip_shift": trip_shift,
                "contact": contact,
            },
        )

        self.stdout.write(self.style.SUCCESS("Seeded Bike for a Better San Diego demo."))
        self.stdout.write(f"Survey URL: /surveys/{survey.uuid}/")
        self.stdout.write("Admin login: sdbike_admin / sdbike-demo-admin")

    def _seed_sample_responses(self, survey, q):
        from survey.models import SurveySession

        SurveySession.objects.filter(survey=survey, tags__contains=["demo_seed"]).delete()

        samples = [
            {
                "area": "City Heights",
                "rider": [1, 3],
                "point": (-117.1053, 32.7551),
                "hazard_type": 2,
                "note": "Families avoid this crossing during school drop-off.",
                "line": [(-117.1090, 32.7544), (-117.1192, 32.7557), (-117.1283, 32.7550)],
                "purpose": [1, 2],
                "priority": 1,
                "shift": 3,
            },
            {
                "area": "North Park",
                "rider": [1, 2],
                "point": (-117.1298, 32.7486),
                "hazard_type": 3,
                "note": "The bike lane disappears right before a busy merge.",
                "line": [(-117.1424, 32.7476), (-117.1352, 32.7481), (-117.1250, 32.7487)],
                "purpose": [3, 5],
                "priority": 2,
                "shift": 4,
            },
            {
                "area": "Chula Vista",
                "rider": [4, 5],
                "point": (-117.0842, 32.6401),
                "hazard_type": 1,
                "note": "Fast traffic makes this feel impossible for new riders.",
                "line": [(-117.0908, 32.6415), (-117.0809, 32.6401), (-117.0710, 32.6378)],
                "purpose": [2, 4],
                "priority": 2,
                "shift": 2,
            },
            {
                "area": "La Mesa",
                "rider": [1],
                "point": (-117.0231, 32.7672),
                "hazard_type": 4,
                "note": "Loading and parking conflicts push riders into traffic.",
                "line": [(-117.0304, 32.7668), (-117.0231, 32.7672), (-117.0155, 32.7681)],
                "purpose": [2, 3, 5],
                "priority": 3,
                "shift": 2,
            },
            {
                "area": "Oceanside",
                "rider": [2, 3],
                "point": (-117.3795, 33.1959),
                "hazard_type": 2,
                "note": "Beach route crossings need clearer driver yielding.",
                "line": [(-117.3853, 33.1967), (-117.3770, 33.1960), (-117.3662, 33.1944)],
                "purpose": [1, 4],
                "priority": 4,
                "shift": 1,
            },
            {
                "area": "San Ysidro",
                "rider": [1, 5],
                "point": (-117.0431, 32.5528),
                "hazard_type": 3,
                "note": "A protected connection would make cross-border trips less stressful.",
                "line": [(-117.0507, 32.5520), (-117.0431, 32.5528), (-117.0342, 32.5557)],
                "purpose": [2, 3],
                "priority": 5,
                "shift": 5,
            },
        ]

        for sample in samples:
            session = SurveySession.objects.create(
                survey=survey,
                start_datetime=timezone.now(),
                end_datetime=timezone.now(),
                validation_status="approved",
                tags=["demo_seed"],
                notes="Seeded sample response for the executive demo.",
            )
            Answer.objects.create(survey_session=session, question=q["rider_type"], selected_choices=sample["rider"])
            Answer.objects.create(survey_session=session, question=q["home_area"], text=sample["area"])

            hazard_answer = Answer.objects.create(
                survey_session=session,
                question=q["hazard"],
                point=Point(*sample["point"]),
            )
            Answer.objects.create(
                survey_session=session,
                question=q["hazard_type"],
                parent_answer_id=hazard_answer,
                selected_choices=[sample["hazard_type"]],
            )
            Answer.objects.create(
                survey_session=session,
                question=q["hazard_note"],
                parent_answer_id=hazard_answer,
                text=sample["note"],
            )

            route_answer = Answer.objects.create(
                survey_session=session,
                question=q["route"],
                line=LineString(*sample["line"]),
            )
            Answer.objects.create(
                survey_session=session,
                question=q["route_purpose"],
                parent_answer_id=route_answer,
                selected_choices=sample["purpose"],
            )

            Answer.objects.create(survey_session=session, question=q["top_priority"], selected_choices=[sample["priority"]])
            Answer.objects.create(survey_session=session, question=q["trip_shift"], numeric=sample["shift"])
            Answer.objects.create(survey_session=session, question=q["contact"], text="")
