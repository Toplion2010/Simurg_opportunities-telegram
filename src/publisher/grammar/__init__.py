"""Grammar Engine — behavior only, no appearance (ADR-003).

Decides layout, what to show, what to shrink, and what to drop,
based on content and background.  Grammar decides position, size,
presence.  It never decides colors — those come from the Design System.

Modules:
    layout     — Layout strategy config objects
    priority   — Category default + override field ordering
    responsive — Font-size, truncation, density switches
    visibility — What to drop when the card is overloaded
"""
