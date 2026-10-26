package cl.rentacompa.identity;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.core.JsonParser;
import jakarta.ws.rs.BadRequestException;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.ForbiddenException;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.NotAuthorizedException;
import jakarta.ws.rs.NotFoundException;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.Provider;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Stream;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.UserModel;
import org.keycloak.models.UserSessionModel;
import org.keycloak.services.managers.AppAuthManager;
import org.keycloak.util.JsonSerialization;

/** Only session identifiers cross this boundary; no names, IPs, tokens or profiles. */
@Provider
@Produces(MediaType.APPLICATION_JSON)
public final class SessionResource {
    private static final String AUDIENCE = "rac-session-control";
    private static final String CLIENT = "rac-standing-sessions";
    private static final int MAX_SNAPSHOT = 4096;
    private static final int MAX_BATCH = 100;
    private static final int MAX_BODY = 16384;
    private final KeycloakSession session;

    public SessionResource(KeycloakSession session) { this.session = session; }

    private void authorize() {
        var auth = new AppAuthManager.BearerTokenAuthenticator(session).setAudience(AUDIENCE).authenticate();
        if (auth == null) throw new NotAuthorizedException("Bearer");
        var roles = auth.token().getResourceAccess(AUDIENCE);
        if (auth.client() == null || !CLIENT.equals(auth.client().getClientId())
                || !CLIENT.equals(auth.token().getIssuedFor())
                || !auth.client().getId().equals(auth.user().getServiceAccountClientLink())
                || !auth.client().isServiceAccountsEnabled()
                || roles == null || !roles.isUserInRole("sessions.revoke")) {
            throw new ForbiddenException();
        }
    }

    private static String identifier(String value) {
        try {
            if (value == null || !UUID.fromString(value).toString().equals(value)
                    || value.equals("00000000-0000-0000-0000-000000000000")) throw new IllegalArgumentException();
            return value;
        } catch (IllegalArgumentException error) { throw new BadRequestException(); }
    }

    private UserModel user(String subject) {
        var user = session.users().getUserById(session.getContext().getRealm(), identifier(subject));
        // Do not permit the worker to terminate another technical identity.
        if (user != null && user.getServiceAccountClientLink() != null) throw new ForbiddenException();
        return user;
    }

    private static Response response(Object value) {
        return Response.ok(value).header("Cache-Control", "no-store").build();
    }

    public record SessionRef(String id, boolean offline) { }

    @GET
    @Path("status")
    public Response status() {
        authorize();
        return response(Map.of("schema_version", 1));
    }

    private static String sessionIdentifier(String value) {
        // Session IDs are opaque provider identifiers, not necessarily UUIDs.
        // They are passed as JSON to model lookups, never concatenated into SQL
        // or URLs. Bound them without assuming Keycloak's generation format.
        if (value == null || value.isEmpty() || value.length() > 256
                || value.chars().anyMatch(c -> c <= 32 || c > 126)) {
            throw new BadRequestException("invalid_session_reference");
        }
        return value;
    }

    @GET
    @Path("users/{subject}/sessions")
    public Response snapshot(@PathParam("subject") String subject) {
        authorize();
        var user = user(subject);
        if (user == null) throw new NotFoundException();
        RealmModel realm = session.getContext().getRealm();
        List<SessionRef> refs = new ArrayList<>();
        try (Stream<UserSessionModel> online = session.sessions().getUserSessionsStream(realm, user);
             Stream<UserSessionModel> offline = session.sessions().getOfflineUserSessionsStream(realm, user)) {
            Stream.concat(online.map(s -> new SessionRef(s.getId(), false)),
                          offline.map(s -> new SessionRef(s.getId(), true)))
                .limit(MAX_SNAPSHOT + 1L).forEach(refs::add);
        }
        // Never truncate and claim a complete capture. No mutation on overflow.
        if (refs.size() > MAX_SNAPSHOT) throw new WebApplicationException(409);
        refs.sort(java.util.Comparator.comparing(SessionRef::id).thenComparing(SessionRef::offline));
        return response(Map.of("sessions", refs, "complete", true));
    }

    @POST
    @Path("users/{subject}/sessions/revoke")
    @Consumes(MediaType.APPLICATION_JSON)
    public Response revoke(@PathParam("subject") String subject, InputStream input) {
        authorize();
        identifier(subject);
        JsonNode body;
        try {
            byte[] bytes = input.readNBytes(MAX_BODY + 1);
            if (bytes.length > MAX_BODY) throw new WebApplicationException(413);
            body = JsonSerialization.mapper.reader()
                .with(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
                .with(JsonParser.Feature.STRICT_DUPLICATE_DETECTION).readTree(bytes);
        } catch (IOException error) { throw new BadRequestException("invalid_session_payload"); }
        if (body == null || !body.isObject() || body.size() != 1 || !body.has("sessions")
                || !body.get("sessions").isArray() || body.get("sessions").isEmpty()
                || body.get("sessions").size() > MAX_BATCH) throw new BadRequestException("invalid_session_batch");
        var refs = new ArrayList<SessionRef>();
        var unique = new HashSet<SessionRef>();
        for (JsonNode item : body.get("sessions")) {
            if (!item.isObject() || item.size() != 2 || !item.has("id") || !item.get("id").isTextual()
                    || !item.has("offline") || !item.get("offline").isBoolean()) throw new BadRequestException("invalid_session_reference");
            var ref = new SessionRef(sessionIdentifier(item.get("id").asText()), item.get("offline").asBoolean());
            if (!unique.add(ref)) throw new BadRequestException();
            refs.add(ref);
        }
        var user = user(subject);
        if (user == null) return response(Map.of("removed", 0, "missing", refs.size()));
        RealmModel realm = session.getContext().getRealm();
        var models = new ArrayList<UserSessionModel>();
        // Resolve and validate the whole batch BEFORE any deletion. Mixing a
        // foreign user's session into a valid batch must not partially revoke it.
        for (SessionRef ref : refs) {
            var model = ref.offline() ? session.sessions().getOfflineUserSession(realm, ref.id())
                                      : session.sessions().getUserSession(realm, ref.id());
            if (model != null && !subject.equals(model.getUser().getId())) throw new ForbiddenException();
            models.add(model);
        }
        int removed = 0;
        for (int i = 0; i < refs.size(); i++) {
            var model = models.get(i);
            if (model == null) continue;
            // Invalidate precisely the selected session, including refresh and
            // SSO. No user/realm not-before, offline counterpart, broker logout
            // or role changes that could affect a new, unselected login.
            if (refs.get(i).offline()) session.sessions().removeOfflineUserSession(realm, model);
            else session.sessions().removeUserSession(realm, model);
            removed++;
        }
        return response(Map.of("removed", removed, "missing", refs.size() - removed));
    }
}
