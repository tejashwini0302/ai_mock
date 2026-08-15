from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    PageBreak,
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def safe_text(value):
    if value is None:
        return ""

    if isinstance(value, bool):
        return "Yes" if value else "No"

    return escape(str(value))


def bullet_text(items):
    if not items:
        return "No information available."

    return "<br/>".join(
        f"• {safe_text(item)}"
        for item in items
        if item
    )


# ---------------------------------------------------------
# PDF generation
# ---------------------------------------------------------

def generate_pdf(result: dict, username: str = "", created_at: str = "") -> bytes:

    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=16 * mm,
        leftMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Placement-Ready AI Career Report",
        author="Placement-Ready AI Career Agent",
    )

    styles = getSampleStyleSheet()

    # -----------------------------------------------------
    # Styles
    # -----------------------------------------------------

    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=21,
        leading=25,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#172033"),
        spaceAfter=5,
    )

    subtitle_style = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        leading=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=10,
    )

    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#172033"),
        spaceBefore=8,
        spaceAfter=8,
    )

    subheading_style = ParagraphStyle(
        "Subheading",
        parent=styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10.5,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceBefore=5,
        spaceAfter=5,
    )

    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9.2,
        leading=14,
        textColor=colors.HexColor("#334155"),
        spaceAfter=5,
    )

    small_style = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#64748b"),
    )

    score_number_style = ParagraphStyle(
        "ScoreNumber",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=22,
        leading=25,
        alignment=TA_CENTER,
        textColor=colors.white,
    )

    score_label_style = ParagraphStyle(
        "ScoreLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#334155"),
    )

    job_title_style = ParagraphStyle(
        "JobTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#172033"),
    )

    # -----------------------------------------------------
    # Page footer
    # -----------------------------------------------------

    def add_footer(canvas, doc):
        canvas.saveState()

        width, height = A4

        canvas.setStrokeColor(colors.HexColor("#e2e8f0"))
        canvas.setLineWidth(0.5)
        canvas.line(
            16 * mm,
            10 * mm,
            width - 16 * mm,
            10 * mm,
        )

        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#94a3b8"))

        canvas.drawString(
            16 * mm,
            6 * mm,
            "Placement-Ready AI Career Agent",
        )

        canvas.drawRightString(
            width - 16 * mm,
            6 * mm,
            f"Page {doc.page}",
        )

        canvas.restoreState()

    # -----------------------------------------------------
    # Data
    # -----------------------------------------------------

    role = result.get("role", "Not specified")
    github_username = result.get("github_username", "Not specified")

    ats_score = result.get("ats_score", 0)
    placement_score = result.get("placement_readiness", 0)
    github_score = result.get("github_score", 0)

    ats_method = result.get(
        "ats_score_method",
        "Not specified"
    )

    ats_feedback = result.get(
        "ats_feedback",
        "No ATS feedback available."
    )

    missing_skills = result.get("missing_skills") or []
    github_recommendations = result.get(
        "github_recommendations"
    ) or []

    projects = result.get("projects") or []
    roadmap = result.get("roadmap") or []
    jobs = result.get("jobs") or []

    github_repos = result.get(
        "github_public_repos",
        0
    )

    github_followers = result.get(
        "github_followers",
        0
    )

    github_languages = result.get(
        "github_top_languages"
    ) or []

    # -----------------------------------------------------
    # Story / document
    # -----------------------------------------------------

    story = []

    # -----------------------------------------------------
    # Header
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "PLACEMENT-READY AI CAREER REPORT",
            title_style,
        )
    )

    story.append(
        Paragraph(
            f"Personalized career analysis for <b>{safe_text(role)}</b>",
            subtitle_style,
        )
    )

    candidate_data = [
        [
            Paragraph("<b>Candidate</b>", body_style),
            Paragraph(safe_text(username or "Candidate"), body_style),
        ],
        [
            Paragraph("<b>Target Role</b>", body_style),
            Paragraph(safe_text(role), body_style),
        ],
        [
            Paragraph("<b>GitHub</b>", body_style),
            Paragraph(safe_text(github_username), body_style),
        ],
        [
            Paragraph("<b>Generated</b>", body_style),
            Paragraph(safe_text(created_at), body_style),
        ],
    ]

    candidate_table = Table(
        candidate_data,
        colWidths=[38 * mm, 140 * mm],
    )

    candidate_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#f1f5f9"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor("#cbd5e1"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#e2e8f0"),
                ),
                (
                    "VALIGN",
                    (0, 0),
                    (-1, -1),
                    "MIDDLE",
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    5,
                ),
            ]
        )
    )

    story.append(candidate_table)
    story.append(Spacer(1, 9))

    # -----------------------------------------------------
    # Score summary
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "1. SCORE SUMMARY",
            section_style,
        )
    )

    score_data = []

    for label, value in [
        ("ATS SCORE", ats_score),
        ("PLACEMENT READINESS", placement_score),
        ("GITHUB SCORE", github_score),
    ]:

        score_box = Table(
            [
                [
                    Paragraph(
                        str(value),
                        score_number_style,
                    )
                ],
                [
                    Paragraph(
                        label,
                        score_label_style,
                    )
                ],
            ],
            colWidths=[55 * mm],
            rowHeights=[18 * mm, 9 * mm],
        )

        score_box.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#2563eb"),
                    ),
                    (
                        "BACKGROUND",
                        (0, 1),
                        (-1, 1),
                        colors.HexColor("#f8fafc"),
                    ),
                    (
                        "BOX",
                        (0, 0),
                        (-1, -1),
                        0.7,
                        colors.HexColor("#cbd5e1"),
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "MIDDLE",
                    ),
                    (
                        "ALIGN",
                        (0, 0),
                        (-1, -1),
                        "CENTER",
                    ),
                ]
            )
        )

        score_data.append(score_box)

    score_table = Table(
        [score_data],
        colWidths=[57 * mm, 57 * mm, 57 * mm],
    )

    score_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    story.append(score_table)

    story.append(
        Spacer(1, 6)
    )

    story.append(
        Paragraph(
            f"<b>ATS method:</b> {safe_text(ats_method)}",
            small_style,
        )
    )

    # -----------------------------------------------------
    # ATS analysis
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "2. ATS ANALYSIS",
            section_style,
        )
    )

    ats_box = Table(
        [
            [
                Paragraph(
                    safe_text(ats_feedback),
                    body_style,
                )
            ]
        ],
        colWidths=[171 * mm],
    )

    ats_box.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor("#f8fafc"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor("#cbd5e1"),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
            ]
        )
    )

    story.append(ats_box)

    # -----------------------------------------------------
    # Missing skills
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "3. SKILL GAP ANALYSIS",
            section_style,
        )
    )

    if missing_skills:
        skill_rows = [
            [
                Paragraph(
                    f"<b>{safe_text(skill)}</b>",
                    body_style,
                )
            ]
            for skill in missing_skills
        ]

        skill_table = Table(
            skill_rows,
            colWidths=[171 * mm],
        )

        skill_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, -1),
                        colors.HexColor("#fff7ed"),
                    ),
                    (
                        "BOX",
                        (0, 0),
                        (-1, -1),
                        0.6,
                        colors.HexColor("#fed7aa"),
                    ),
                    (
                        "INNERGRID",
                        (0, 0),
                        (-1, -1),
                        0.3,
                        colors.HexColor("#fed7aa"),
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        10,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        6,
                    ),
                ]
            )
        )

        story.append(skill_table)
    else:
        story.append(
            Paragraph(
                "No major skill gaps were identified.",
                body_style,
            )
        )

    # -----------------------------------------------------
    # GitHub
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "4. GITHUB ANALYSIS",
            section_style,
        )
    )

    github_data = [
        [
            Paragraph("<b>Public repositories</b>", body_style),
            Paragraph(str(github_repos), body_style),
        ],
        [
            Paragraph("<b>Followers</b>", body_style),
            Paragraph(str(github_followers), body_style),
        ],
        [
            Paragraph("<b>Top languages</b>", body_style),
            Paragraph(
                safe_text(", ".join(github_languages))
                if github_languages
                else "Not available",
                body_style,
            ),
        ],
    ]

    github_table = Table(
        github_data,
        colWidths=[55 * mm, 116 * mm],
    )

    github_table.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (0, -1),
                    colors.HexColor("#f1f5f9"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor("#cbd5e1"),
                ),
                (
                    "INNERGRID",
                    (0, 0),
                    (-1, -1),
                    0.4,
                    colors.HexColor("#e2e8f0"),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    8,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    6,
                ),
            ]
        )
    )

    story.append(github_table)

    story.append(
        Paragraph(
            "GitHub recommendations",
            subheading_style,
        )
    )

    story.append(
        Paragraph(
            bullet_text(github_recommendations),
            body_style,
        )
    )

    # -----------------------------------------------------
    # Projects
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "5. RECOMMENDED PROJECTS",
            section_style,
        )
    )

    if projects:

        project_rows = []

        for index, project in enumerate(projects, 1):
            project_rows.append(
                [
                    Paragraph(
                        f"<b>Project {index}</b>",
                        body_style,
                    ),
                    Paragraph(
                        safe_text(project),
                        body_style,
                    ),
                ]
            )

        project_table = Table(
            project_rows,
            colWidths=[30 * mm, 141 * mm],
        )

        project_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (0, -1),
                        colors.HexColor("#eff6ff"),
                    ),
                    (
                        "BOX",
                        (0, 0),
                        (-1, -1),
                        0.6,
                        colors.HexColor("#bfdbfe"),
                    ),
                    (
                        "INNERGRID",
                        (0, 0),
                        (-1, -1),
                        0.4,
                        colors.HexColor("#dbeafe"),
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "TOP",
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        8,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                ]
            )
        )

        story.append(project_table)

    else:
        story.append(
            Paragraph(
                "No project recommendations available.",
                body_style,
            )
        )

    # -----------------------------------------------------
    # Roadmap
    # -----------------------------------------------------

    story.append(
        Paragraph(
            "6. PERSONALIZED ROADMAP",
            section_style,
        )
    )

    if roadmap:

        roadmap_rows = [
            [
                Paragraph("<b>Week</b>", body_style),
                Paragraph("<b>Focus</b>", body_style),
                Paragraph("<b>Tasks</b>", body_style),
            ]
        ]

        for item in roadmap:
            if isinstance(item, dict):
                week = item.get("week", "")
                focus = item.get("focus", "")
                tasks = item.get("tasks", "")
            else:
                week = ""
                focus = ""
                tasks = str(item)

            roadmap_rows.append(
                [
                    Paragraph(safe_text(week), body_style),
                    Paragraph(safe_text(focus), body_style),
                    Paragraph(safe_text(tasks), body_style),
                ]
            )

        roadmap_table = Table(
            roadmap_rows,
            colWidths=[27 * mm, 38 * mm, 106 * mm],
            repeatRows=1,
        )

        roadmap_table.setStyle(
            TableStyle(
                [
                    (
                        "BACKGROUND",
                        (0, 0),
                        (-1, 0),
                        colors.HexColor("#172033"),
                    ),
                    (
                        "TEXTCOLOR",
                        (0, 0),
                        (-1, 0),
                        colors.white,
                    ),
                    (
                        "BOX",
                        (0, 0),
                        (-1, -1),
                        0.6,
                        colors.HexColor("#cbd5e1"),
                    ),
                    (
                        "INNERGRID",
                        (0, 0),
                        (-1, -1),
                        0.4,
                        colors.HexColor("#e2e8f0"),
                    ),
                    (
                        "VALIGN",
                        (0, 0),
                        (-1, -1),
                        "TOP",
                    ),
                    (
                        "LEFTPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                    (
                        "RIGHTPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                    (
                        "TOPPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                    (
                        "BOTTOMPADDING",
                        (0, 0),
                        (-1, -1),
                        7,
                    ),
                ]
            )
        )

        story.append(roadmap_table)

    # -----------------------------------------------------
    # Jobs
    # -----------------------------------------------------

    story.append(
        PageBreak()
    )

    story.append(
        Paragraph(
            "7. JOB RECOMMENDATIONS",
            section_style,
        )
    )

    if jobs:

        for index, job in enumerate(jobs, 1):

            if not isinstance(job, dict):
                continue

            title = job.get("title", "Job opportunity")
            company = job.get("company", "")
            location = job.get("location", "")
            url = job.get("url", "")

            details = []

            if company:
                details.append(
                    f"<b>Company:</b> {safe_text(company)}"
                )

            if location:
                details.append(
                    f"<b>Location:</b> {safe_text(location)}"
                )

            if url:
                details.append(
                    f"<b>Link:</b> {safe_text(url)}"
                )

            job_content = [
                Paragraph(
                    f"{index}. {safe_text(title)}",
                    job_title_style,
                ),
                Paragraph(
                    "<br/>".join(details)
                    if details
                    else "Details unavailable.",
                    body_style,
                ),
            ]

            job_table = Table(
                [[job_content]],
                colWidths=[171 * mm],
            )

            job_table.setStyle(
                TableStyle(
                    [
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, -1),
                            colors.HexColor("#f8fafc"),
                        ),
                        (
                            "BOX",
                            (0, 0),
                            (-1, -1),
                            0.6,
                            colors.HexColor("#cbd5e1"),
                        ),
                        (
                            "LEFTPADDING",
                            (0, 0),
                            (-1, -1),
                            10,
                        ),
                        (
                            "RIGHTPADDING",
                            (0, 0),
                            (-1, -1),
                            10,
                        ),
                        (
                            "TOPPADDING",
                            (0, 0),
                            (-1, -1),
                            8,
                        ),
                        (
                            "BOTTOMPADDING",
                            (0, 0),
                            (-1, -1),
                            8,
                        ),
                    ]
                )
            )

            story.append(
                KeepTogether(
                    [
                        job_table,
                        Spacer(1, 7),
                    ]
                )
            )

    else:
        story.append(
            Paragraph(
                "No job recommendations available.",
                body_style,
            )
        )

    # -----------------------------------------------------
    # Final note
    # -----------------------------------------------------

    story.append(
        Spacer(1, 10)
    )

    final_note = Table(
        [
            [
                Paragraph(
                    "<b>Next step:</b> Use this report as your placement action plan. "
                    "Improve the identified skill gaps, strengthen your GitHub profile, "
                    "complete the recommended projects, and apply to relevant roles.",
                    body_style,
                )
            ]
        ],
        colWidths=[171 * mm],
    )

    final_note.setStyle(
        TableStyle(
            [
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, -1),
                    colors.HexColor("#eff6ff"),
                ),
                (
                    "BOX",
                    (0, 0),
                    (-1, -1),
                    0.6,
                    colors.HexColor("#93c5fd"),
                ),
                (
                    "LEFTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "RIGHTPADDING",
                    (0, 0),
                    (-1, -1),
                    10,
                ),
                (
                    "TOPPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
                (
                    "BOTTOMPADDING",
                    (0, 0),
                    (-1, -1),
                    9,
                ),
            ]
        )
    )

    story.append(final_note)

    # -----------------------------------------------------
    # Build PDF
    # -----------------------------------------------------

    doc.build(
        story,
        onFirstPage=add_footer,
        onLaterPages=add_footer,
    )

    buffer.seek(0)

    return buffer.getvalue()
