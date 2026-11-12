from __future__ import annotations

import factory

from apps.accounts.models import Role, User
from apps.customers.models import Customer, CustomerMembership, CustomerSourceMapping
from apps.integrations.models import IntegrationInstance

TEST_PASSWORD = "Correct-Horse-Battery-9!"


def role(key: str) -> Role:
    return Role.objects.get(key=key)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.test")
    display_name = factory.Faker("name")
    is_active = True

    @factory.post_generation
    def password(self, create: bool, extracted: str | None, **kwargs: object) -> None:
        self.set_password(extracted or TEST_PASSWORD)
        if create:
            self.save()


class CustomerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Customer

    code = factory.Sequence(lambda n: f"CUST{n:03d}")
    name = factory.Sequence(lambda n: f"Customer {n}")
    status = Customer.Status.ACTIVE


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CustomerMembership

    customer = factory.SubFactory(CustomerFactory)
    user = factory.SubFactory(UserFactory)
    role = factory.LazyFunction(lambda: role("engineer"))


class IntegrationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = IntegrationInstance

    name = factory.Sequence(lambda n: f"Fixture VSA {n}")
    provider = IntegrationInstance.Provider.VSA_X
    base_url = factory.Sequence(lambda n: f"https://vsa{n}.invalid")
    is_fixture = True


class MappingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CustomerSourceMapping

    customer = factory.SubFactory(CustomerFactory)
    integration_instance = factory.SubFactory(IntegrationFactory)
    external_org_id = factory.Sequence(lambda n: f"org-{n}")
    mapping_status = CustomerSourceMapping.Status.PROPOSED
