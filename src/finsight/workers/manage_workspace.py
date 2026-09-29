"""Local operator-only workspace, membership, and knowledge-scope setup."""

from argparse import ArgumentParser
from uuid import UUID

from finsight.domain.access_control import Role
from finsight.infrastructure.database.session import SessionFactory
from finsight.services.identity import IdentityService


def main() -> int:
    parser = ArgumentParser(description="Manage local workspaces and memberships")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create a workspace")
    create.add_argument("--name", required=True)
    grant = commands.add_parser("grant", help="Assign one workspace role to an existing user")
    grant.add_argument("--email", required=True)
    grant.add_argument("--workspace-id", type=UUID, required=True)
    grant.add_argument("--role", type=Role, choices=list(Role), required=True)
    knowledge_create = commands.add_parser("knowledge-create", help="Create a knowledge base")
    knowledge_create.add_argument("--workspace-id", type=UUID, required=True)
    knowledge_create.add_argument("--name", required=True)
    knowledge_grant = commands.add_parser("knowledge-grant", help="Grant a user one knowledge base")
    knowledge_grant.add_argument("--email", required=True)
    knowledge_grant.add_argument("--knowledge-base-id", type=UUID, required=True)
    document_link = commands.add_parser("document-link", help="Link a document to one knowledge base")
    document_link.add_argument("--knowledge-base-id", type=UUID, required=True)
    document_link.add_argument("--document-id", type=int, required=True)
    args = parser.parse_args()
    identity = IdentityService(SessionFactory)
    try:
        if args.command == "create":
            print(f"Created workspace {identity.create_workspace(args.name)}")
        elif args.command == "grant":
            user_id = identity.user_id_for_email(args.email)
            identity.assign_role(user_id, args.workspace_id, args.role)
            print(f"Assigned {args.role.value} to user {user_id} in {args.workspace_id}")
        elif args.command == "knowledge-create":
            base_id = identity.create_knowledge_base(args.workspace_id, args.name)
            print(f"Created knowledge base {base_id} in {args.workspace_id}")
        elif args.command == "knowledge-grant":
            user_id = identity.user_id_for_email(args.email)
            identity.grant_knowledge_base(user_id, args.knowledge_base_id)
            print(f"Granted knowledge base {args.knowledge_base_id} to user {user_id}")
        elif args.command == "document-link":
            identity.link_document(args.knowledge_base_id, args.document_id)
            print(f"Linked document {args.document_id} to {args.knowledge_base_id}")
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
