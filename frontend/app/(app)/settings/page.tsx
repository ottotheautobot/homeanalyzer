import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { serverFetch } from "@/lib/api-server";
import type { Me } from "@/lib/types";

import { SavedLocationsForm } from "./saved-locations";
import { SettingsForm } from "./settings-form";

export default async function SettingsPage() {
  const me = await serverFetch<Me>("/me");
  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Per-account preferences. Changes apply to every tour you start.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Profile</CardTitle>
        </CardHeader>
        <CardContent>
          <SettingsForm
            initial={{
              email: me.email,
              name: me.name ?? "",
              default_zoom_url: me.default_zoom_url ?? "",
            }}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Saved locations</CardTitle>
        </CardHeader>
        <CardContent>
          <SavedLocationsForm initial={me.saved_locations ?? []} />
        </CardContent>
      </Card>
    </div>
  );
}
