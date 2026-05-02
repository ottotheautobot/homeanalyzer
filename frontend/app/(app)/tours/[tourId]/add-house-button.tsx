"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";

import { NewHouseForm } from "./new-house-form";

export function AddHouseButton({
  tourId,
  variant = "primary",
}: {
  tourId: string;
  /** "primary" sits in the page header next to the title; "empty" is
   *  the larger CTA shown when the houses list is empty. */
  variant?: "primary" | "empty";
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {variant === "primary" ? (
        <Button size="sm" onClick={() => setOpen(true)}>
          <Plus strokeWidth={2.5} />
          <span>Add house</span>
        </Button>
      ) : (
        <Button onClick={() => setOpen(true)}>
          <Plus strokeWidth={2.5} />
          <span>Add the first house</span>
        </Button>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="Add a house">
        <NewHouseForm tourId={tourId} onSubmitted={() => setOpen(false)} />
      </Modal>
    </>
  );
}
