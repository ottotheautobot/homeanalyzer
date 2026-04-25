import Link from "next/link";

import { Button, buttonVariants } from "@/components/ui/button";
import { createSupabaseServerClient } from "@/lib/supabase/server";
import { signOut } from "@/app/actions/auth";

export default async function Home() {
  const supabase = await createSupabaseServerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <main className="flex flex-1 flex-col items-center justify-center p-8">
      <div className="w-full max-w-md space-y-6 text-center">
        <h1 className="text-3xl font-semibold tracking-tight">
          House Tour Notes
        </h1>

        {user ? (
          <>
            <p className="text-zinc-600 dark:text-zinc-400">
              Signed in as <span className="font-medium">{user.email}</span>
            </p>
            <form action={signOut}>
              <Button type="submit" variant="outline">
                Sign out
              </Button>
            </form>
          </>
        ) : (
          <>
            <p className="text-zinc-600 dark:text-zinc-400">
              Sign in to start a tour.
            </p>
            <Link href="/login" className={buttonVariants()}>
              Sign in
            </Link>
          </>
        )}
      </div>
    </main>
  );
}
