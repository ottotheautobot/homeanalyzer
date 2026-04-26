-- list_price could be either a sale price or monthly rent; price_kind
-- distinguishes them so the UI shows '$X' vs '$X/mo' and the brief / compare
-- prompts can interpret correctly.

alter table public.houses
    add column if not exists price_kind text default 'sale'
    check (price_kind in ('sale', 'rent'));
