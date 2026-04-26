-- Add 'friend_family' to the role check on users / tour_participants /
-- tour_invites so we can invite people who aren't co-buyers, partners,
-- or agents (parents, siblings, friends giving an opinion, etc.).

alter table public.users
    drop constraint if exists users_role_check;
alter table public.users
    add constraint users_role_check
    check (role in ('buyer', 'partner', 'agent', 'friend_family'));

alter table public.tour_participants
    drop constraint if exists tour_participants_role_check;
alter table public.tour_participants
    add constraint tour_participants_role_check
    check (role in ('buyer', 'partner', 'agent', 'friend_family'));

alter table public.tour_invites
    drop constraint if exists tour_invites_role_check;
alter table public.tour_invites
    add constraint tour_invites_role_check
    check (role in ('buyer', 'partner', 'agent', 'friend_family'));
