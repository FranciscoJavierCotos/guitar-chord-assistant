import ResetPasswordForm from "@/components/ResetPasswordForm";

export const metadata = { title: "Reset password · ChordCoach" };

export default function ResetPasswordPage() {
  return (
    <main className="flex min-h-full items-center justify-center bg-bg-primary px-4 py-12">
      <ResetPasswordForm />
    </main>
  );
}
