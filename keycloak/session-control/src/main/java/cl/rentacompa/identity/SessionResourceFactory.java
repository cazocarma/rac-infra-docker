package cl.rentacompa.identity;

import jakarta.ws.rs.NotFoundException;
import org.keycloak.Config;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.services.resource.RealmResourceProvider;
import org.keycloak.services.resource.RealmResourceProviderFactory;

/** Opt-in identity adapter. No realm-management credentials or custom JPA model. */
public final class SessionResourceFactory implements RealmResourceProviderFactory {
    private boolean active;

    @Override public String getId() { return "rac-sessions"; }
    @Override public void init(Config.Scope config) { active = config.getBoolean("active", false); }
    @Override public void postInit(KeycloakSessionFactory factory) { }
    @Override public void close() { }

    @Override public RealmResourceProvider create(KeycloakSession session) {
        return new RealmResourceProvider() {
            @Override public Object getResource() {
                if (!active || !"rentacompa".equals(session.getContext().getRealm().getName())) {
                    throw new NotFoundException();
                }
                return new SessionResource(session);
            }
            @Override public void close() { }
        };
    }
}
