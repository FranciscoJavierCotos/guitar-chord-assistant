import UpdatePasswordForm from "@/components/UpdatePasswordForm";

export const metadata = { title: "Update password · ChordCoach" };

export default function UpdatePasswordPage() {
  return (
    <main className="flex min-h-full items-center justify-center bg-bg-primary px-4 py-12">
      <UpdatePasswordForm />
    </main>
  );
}
