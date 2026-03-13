# Implementation Plan: UI Fixes + Polls/Voting Feature

## Part 1: Immediate UI Fixes (3 tasks)

### 1A. Mobile movie search breaks to its own line
**Problem**: `.filter-search-wrap` has `flex: 1 1 0` on mobile which can push it to a new row when Theatres + Members + search don't fit in one line.
**Fix**: Change `filter-search-wrap` on mobile to `flex: 1 1 0; min-width: 40px` and remove the `max-width` on desktop so it dynamically shrinks. Also position movie dropdown menu to stay on-screen (use `right: 0` when near right edge).

**Files**: `frontend/src/index.css`

### 1B. Filter checkbox color + Select All for Members/Theatres
**Problem**: Checkboxes in filter dropdowns need amber-matching color (already styled with `--amber` on checked — verify). Members dropdown needs a "Select All" button like Movies has.
**Fix**: Add `filter-select-all` button to Members dropdown in Calendar.jsx, and also to Theatres dropdown. Verify checkbox `:checked` uses `var(--amber)` (it already does per line 309).

**Files**: `frontend/src/pages/Calendar.jsx`

### 1C. Pending member alignment on Members page
**Problem**: Pending members in `GroupMembers.jsx` use `.group-member-row.pending` which has `padding: 0.5rem 1rem` matching clickable rows, but they may not align because `.group-member-row` base has `padding: 0.4rem 0` (no horizontal padding). The `.clickable` override adds `padding: 0.5rem 1rem`. The `.pending` class also has `padding: 0.5rem 1rem`, so padding should match. The real issue is likely that pending rows don't have the same left-border space as selected rows.
**Fix**: Ensure `.group-member-row.pending` matches `.group-member-row.clickable` padding exactly. Both should use `padding: 0.5rem 1rem`.

**Files**: `frontend/src/index.css`

### 1D. Browse Groups → Members goes to old popup
**Problem**: `GroupDiscovery.jsx` line 218 navigates to `/members` route correctly. Need to verify this works — the user reports it still opens the old popup. Check if `GroupAdmin` component still uses the overlay version.
**Fix**: Check `GroupAdmin.jsx` for any remaining `GroupMembers` overlay usage and convert to `/members` route navigation.

**Files**: `frontend/src/components/GroupAdmin.jsx` (if it exists and uses GroupMembers overlay)

---

## Part 2: Polls & Voting Feature

### 2A. Backend Data Models (in `backend/app.py`)

```python
class Poll(db.Model):
    id            = Integer, PK
    group_id      = FK → Group
    created_by    = FK → User
    title         = String(200)         # e.g. "98th Academy Awards Predictions"
    description   = Text (optional)
    poll_type     = String(20)          # 'standard' | 'prediction'
    scoring_mode  = String(20)          # 'none' | 'single' | 'ranked' | 'confidence'
    status        = String(20)          # 'open' | 'closed' | 'scored'
    created_at    = DateTime
    closed_at     = DateTime (nullable)

class PollCategory(db.Model):
    id            = Integer, PK
    poll_id       = FK → Poll
    title         = String(200)         # e.g. "Best Picture"
    sort_order    = Integer             # display order
    correct_option_id = Integer (nullable)  # set when winner revealed

class PollOption(db.Model):
    id            = Integer, PK
    category_id   = FK → PollCategory
    text          = String(300)         # e.g. "Anora"
    sort_order    = Integer
    extra_data    = Text (JSON, nullable)  # poster_url, nominee details, etc.

class PollVote(db.Model):
    id            = Integer, PK
    category_id   = FK → PollCategory
    user_id       = FK → User
    option_id     = FK → PollOption
    confidence    = Integer (1-10, default 1)  # used when scoring_mode='confidence'
    rank          = Integer (nullable)          # used when scoring_mode='ranked'
    created_at    = DateTime
    UniqueConstraint('category_id', 'user_id')  # one vote per category per user
```

**Scoring logic** (computed, not stored — or cached on Poll):
- `scoring_mode='none'`: No points awarded
- `scoring_mode='single'`: +1 🍿 per correct pick
- `scoring_mode='ranked'`: Points based on rank position of correct answer (3 for #1, 2 for #2, 1 for #3, 0 otherwise)
- `scoring_mode='confidence'`: confidence × (1 if correct else 0) = kernels earned

**User total score**: Computed by summing all earned kernels across all scored polls in all groups the user belongs to. Displayed on profile.

### 2B. Backend API Routes

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/groups/<gid>/polls` | member | List polls for group |
| POST | `/api/groups/<gid>/polls` | admin | Create poll |
| GET | `/api/polls/<pid>` | member | Get poll detail + categories + options + user's votes |
| PUT | `/api/polls/<pid>` | admin | Update poll (close, edit) |
| DELETE | `/api/polls/<pid>` | admin | Delete poll |
| POST | `/api/polls/<pid>/vote` | member | Submit votes (array of {category_id, option_id, confidence?, rank?}) |
| POST | `/api/polls/<pid>/score` | admin | Mark winners & compute scores |
| GET | `/api/polls/<pid>/leaderboard` | member | Get ranked leaderboard for poll |
| GET | `/api/users/<uid>/kernels` | any authed | Get user's total kernel count |
| POST | `/api/groups/<gid>/polls/oscars` | admin | Create Oscars poll from template |

### 2C. Oscars Template (`backend/oscars_2026.json`)

Static JSON structured as:
```json
{
  "title": "98th Academy Awards Predictions",
  "year": 2026,
  "ceremony_date": "2026-03-01",
  "categories": [
    {
      "title": "Best Picture",
      "nominees": [
        { "text": "Anora", "extra": { "poster_url": "..." } },
        { "text": "The Brutalist" },
        ...
      ]
    },
    {
      "title": "Best Director",
      "nominees": [...]
    },
    ...
  ]
}
```

Categories to include: Best Picture, Best Director, Best Actress, Best Actor, Best Supporting Actress, Best Supporting Actor, Best Animated Feature, Best Original Screenplay, Best Adapted Screenplay, Best International Feature, Best Documentary Feature, Best Cinematography, Best Film Editing, Best Original Score, Best Original Song, Best Production Design, Best Costume Design, Best Makeup and Hairstyling, Best Sound, Best Visual Effects.

### 2D. Frontend Pages

#### `/polls` — PollsPage.jsx
- Header: ← Calendar | Polls | avatar
- Shows list of polls for active group
- Open polls at top, closed/scored below
- Each poll card shows: title, type badge (Standard/Prediction), status, # voted, scoring mode icon
- Admin sees "Create Poll" button + "Oscars Template" button
- Poll card click → navigates to `/polls/:id`

#### `/polls/:id` — PollDetailPage.jsx
- Header: ← Polls | Poll Title | avatar
- **Voting view** (when poll is open & user hasn't voted all categories):
  - Category-by-category card layout
  - Each category shows options as selectable cards/radio buttons
  - If scoring_mode='confidence': slider or number input (1-10) per category
  - If scoring_mode='ranked': drag-to-rank or numbered selects
  - Submit button at bottom
- **Results view** (after voting or when poll is closed):
  - Each category shows vote distribution (bar chart or counts)
  - User's pick highlighted
  - If scored: ✅/❌ on each pick, kernels earned shown
  - Winner highlighted in gold
- **Leaderboard tab/section**:
  - Ranked list of members by 🍿 kernels earned
  - Avatar + name + kernel count
  - Current user highlighted

### 2E. Poll Creation UI (within PollsPage or modal)
- **Standard poll**: Title, description, add options (text inputs), scoring mode selector
- **Prediction poll**: Title, description, add categories → add options per category, scoring mode selector
- **Oscars template**: One-click creates a prediction poll pre-filled from oscars_2026.json
- **Scoring mode selector**: Radio group — None (just for fun), Single (1🍿 per correct), Ranked, Confidence (1-10 × correct)

### 2F. Navigation Integration
- Add "Polls" link in GroupSwitcher dropdown (between Members and Browse)
- Add `/polls` and `/polls/:id` routes to App.jsx

### 2G. Kernel Score on User Profile
- Add `total_kernels` computed endpoint (or field)
- Show 🍿 kernel count on user avatar/profile in ProfileMenu, UserProfileDrawer, and MembersPage

### 2H. Group Deletion Cascade
- Add to `delete_group()`: delete PollVote, PollOption, PollCategory, Poll records for group

---

## Implementation Order

1. **UI fixes** (Part 1A-1D) — quick CSS/JSX changes
2. **Backend models + migration** (2A) — add Poll/PollCategory/PollOption/PollVote models, create tables
3. **Backend routes** (2B) — CRUD + voting + scoring + leaderboard
4. **Oscars JSON template** (2C) — static data file
5. **Frontend PollsPage** (2D) — poll list + create form
6. **Frontend PollDetailPage** (2D) — voting + results + leaderboard
7. **Navigation + profile integration** (2F, 2G)
8. **Group deletion cascade** (2H)
9. **Testing on mobile + desktop**

## Files to Create
- `backend/oscars_2026.json`
- `frontend/src/pages/PollsPage.jsx`
- `frontend/src/pages/PollDetailPage.jsx`

## Files to Modify
- `backend/app.py` (models, routes, delete cascade)
- `frontend/src/App.jsx` (routes)
- `frontend/src/pages/Calendar.jsx` (Select All buttons for Members/Theatres)
- `frontend/src/index.css` (filter fixes, poll styles, pending member alignment)
- `frontend/src/components/GroupSwitcher.jsx` (Polls nav link)
- `frontend/src/components/GroupAdmin.jsx` (fix Members overlay → route)
- `frontend/src/components/ProfileMenu.jsx` or `UserProfileDrawer.jsx` (kernel display)
