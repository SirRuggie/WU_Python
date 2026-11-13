import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { defaultLeaveTags } from "../strikeSelections";
import { errorText } from "./format";
import type { Member } from "./types";

export default function useLeaveApproval({
  accessLost,
  canView,
  tab,
  setError,
}: {
  accessLost: boolean;
  canView: boolean;
  tab: string;
  setError: (error: string) => void;
}) {
  const memberRequest = useRef(0);
  const [memberQuery, setMemberQuery] = useState("");
  const [memberError, setMemberError] = useState("");
  const [endingLeave, setEndingLeave] = useState("");
  const [members, setMembers] = useState<Member[]>([]);
  const [selectedMember, setSelectedMember] = useState("");
  const [leaveRevision, setLeaveRevision] = useState<number | null>(null);
  const [leaveConflict, setLeaveConflict] = useState(false);
  const [resumeDate, setResumeDate] = useState("");
  const [leaveTags, setLeaveTags] = useState<string[]>([]);
  useEffect(() => {
    if (
      accessLost ||
      !canView ||
      !["history", "leave"].includes(tab) ||
      !memberQuery.trim()
    ) {
      setMembers([]);
      return;
    }
    let active = true;
    setMemberError("");
    const timer = setTimeout(() => {
      void api<{ members: Member[] }>(
        `/strikes/members?query=${encodeURIComponent(memberQuery.trim())}`,
      )
        .then((data) => {
          if (active) setMembers(data.members);
        })
        .catch((cause) => {
          if (active) {
            setMembers([]);
            setMemberError(errorText(cause));
          }
        });
    }, 250);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [accessLost, canView, memberQuery, tab]);
  const chooseMember = async (id: string) => {
    const request = ++memberRequest.current;
    setLeaveTags([]);
    setLeaveRevision(null);
    setLeaveConflict(false);
    setSelectedMember(id);
    if (!id) {
      setLeaveTags([]);
      return;
    }
    let member: Member;
    try {
      member = (
        await api<{ member: Member }>(
          `/strikes/members/${encodeURIComponent(id)}/accounts`,
        )
      ).member;
      const state = await api<{ revision: number }>(
        `/strikes/settings/leaves/${encodeURIComponent(id)}`,
      );
      if (request !== memberRequest.current) return;
      setLeaveRevision(state.revision);
    } catch (err) {
      if (request === memberRequest.current) setError(errorText(err));
      return;
    }
    if (request !== memberRequest.current) return;
    setMembers((current) =>
      current.map((item) => (item.id === id ? member : item)),
    );
    setLeaveTags(defaultLeaveTags(member?.accounts || []));
  };
  return {
    memberRequest,
    memberQuery,
    setMemberQuery,
    memberError,
    endingLeave,
    setEndingLeave,
    members,
    setMembers,
    selectedMember,
    setSelectedMember,
    leaveRevision,
    setLeaveRevision,
    leaveConflict,
    setLeaveConflict,
    resumeDate,
    setResumeDate,
    leaveTags,
    setLeaveTags,
    chooseMember,
  };
}
